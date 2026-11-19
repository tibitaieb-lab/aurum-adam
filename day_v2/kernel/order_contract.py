"""Versioned order data; expressions are checked by the common compiler.

This contract does not own strategies, positions, cash, price fetching or fills.
"""
from datetime import timedelta
from decimal import Decimal
from .contracts import keys, require, number, stamp, iso, clone

VERSION = 'AURUM_ENTRY_ORDER_V1'
MODEL_VERSION = 'AURUM_CAUSAL_ORDER_EXECUTION_V1'
TYPES = ('MARKET', 'LIMIT', 'STOP', 'STOP_LIMIT')
TIFS = ('AUTO', 'UNTIL_SIGNAL_EXPIRY', 'SESSION_END', 'GTD', 'GTC')
STATES = ('CREATED', 'ACTIVE', 'TRIGGERED', 'FILLED', 'CANCELLED', 'EXPIRED', 'REJECTED')
LIMITATIONS = dict(partial_fill_model='NOT_IMPLEMENTED', queue_position='NOT_MODELED',
                  market_impact='NOT_MODELED', quantity_fill='FULL_FILL_IF_ELIGIBLE',
                  limit_eligibility='TRADE_THROUGH_REQUIRED')


def validate(order, doc, check, requirements):
    keys(order, ('version', 'type', 'time_in_force'), 'day.entry_order',
         optional=('limit_price_rule', 'stop_price_rule', 'good_till'))
    require(order['version'] == VERSION, 'ORDER_VERSION', 'day.entry_order', 'Version d’ordre inconnue.')
    kind = order['type']
    require(kind in TYPES, 'ORDER_TYPE', 'day.entry_order.type', 'MARKET, LIMIT, STOP ou STOP_LIMIT requis.')
    require(order['time_in_force'] in TIFS, 'ORDER_TIF', 'day.entry_order.time_in_force', 'Validité d’ordre inconnue.')
    needed = ({'limit_price_rule'} if kind == 'LIMIT' else {'stop_price_rule'} if kind == 'STOP'
              else {'limit_price_rule', 'stop_price_rule'} if kind == 'STOP_LIMIT' else set())
    actual = set(order) & {'limit_price_rule', 'stop_price_rule'}
    require(actual == needed, 'ORDER_PRICE_FIELDS', 'day.entry_order', 'Renseigner uniquement les niveaux nécessaires au type d’ordre.')
    allowed = {doc['day']['signal_tf'], doc['day'].get('context_tf'), doc['day'].get('trigger_tf')} - {None}
    for field in needed:
        rule = order[field]
        keys(rule, ('expression', 'offset', 'offset_unit'), 'day.entry_order.' + field)
        info = check(rule['expression'], 'day.entry_order.' + field + '.expression')
        require(info.unit == 'PRICE' and info.timeframes <= allowed, 'ORDER_PRICE_TYPE', 'day.entry_order.' + field,
                'Prix sur les séries et timeframes déclarés, disponibles à la décision.')
        number(rule['offset'], 'day.entry_order.' + field + '.offset')
        require(rule['offset_unit'] in ('TICKS', 'PRICE', 'PERCENT'), 'ORDER_OFFSET_UNIT', 'day.entry_order.' + field,
                'Décalage en ticks, unités de prix ou pourcentage du prix de référence.')
        for tf in info.timeframes:
            requirements[tf] = max(requirements.get(tf, 0), info.warmup)
    tif = order['time_in_force']
    require(tif != 'UNTIL_SIGNAL_EXPIRY' or doc['day'].get('signal_ttl') is not None,
            'ORDER_TTL_REQUIRED', 'day.signal_ttl', 'Cette validité exige un TTL du signal.')
    require((tif == 'GTD') == ('good_till' in order), 'ORDER_GTD_REQUIRED', 'day.entry_order.good_till',
            'Une date UTC explicite est requise uniquement pour GTD.')
    if tif == 'GTD': stamp(order['good_till'])
    require(tif != 'GTC' or doc['day']['overnight_policy'] == 'ALLOW', 'ORDER_GTC_OVERNIGHT',
            'day.entry_order.time_in_force', 'GTC incompatible avec l’interdiction overnight.')
    return order


def validate_execution(profile, asset, order, instrument=None):
    keys(profile, ('version', 'id', 'asset', 'trigger_price_basis', 'status', 'reference',
                   'limit_eligibility', 'quantity_fill', 'capacity_at_fill'), 'entry_execution', optional=('instrument_identity',))
    require(profile['version'] == MODEL_VERSION and profile['asset'] == asset, 'ORDER_PROFILE_IDENTITY',
            'entry_execution', 'Profil d’exécution de version et d’instrument exacts requis.')
    require(profile['status'] in ('DOCUMENTED', 'DERIVED', 'MODEL', 'ASSUMED', 'TEST_ONLY')
            and isinstance(profile['reference'], str) and bool(profile['reference'].strip()),
            'ORDER_PROFILE_PROVENANCE', 'entry_execution', 'Statut et provenance du modèle requis.')
    require(profile['limit_eligibility'] == 'TRADE_THROUGH_REQUIRED'
            and profile['quantity_fill'] == 'FULL_FILL_IF_ELIGIBLE'
            and profile['capacity_at_fill'] == 'REJECT_WITHOUT_RESIZING', 'ORDER_MODEL_UNSUPPORTED',
            'entry_execution', 'Franchissement, fill total modélisé et refus sans redimensionnement requis.')
    if profile.get('instrument_identity') is not None:
        identity=profile['instrument_identity']
        keys(identity, ('asset','provider','provider_instrument','product_model','quote_currency'), 'entry_execution.instrument_identity')
        require(all(isinstance(v,str) and v.strip() for v in identity.values()) and identity['asset']==asset,
                'ORDER_INSTRUMENT_IDENTITY','entry_execution','Identité de prix absente ou liée à un autre actif.')
        if instrument is not None:
            require(all(identity[k]==instrument[k] for k in ('product_model','quote_currency')),
                    'ORDER_INSTRUMENT_IDENTITY','entry_execution','Produit ou devise différents de la configuration exécutée.')
    basis = profile['trigger_price_basis']
    require(basis in ('UNKNOWN', 'LAST', 'BID', 'ASK', 'MID', 'BID_ASK', 'PROVIDER_DEFINED'),
            'TRIGGER_REFERENCE_UNKNOWN', 'entry_execution.trigger_price_basis', 'Référence de déclenchement inconnue.')
    if order['type'] in ('STOP', 'STOP_LIMIT'):
        require(basis not in ('UNKNOWN', 'PROVIDER_DEFINED'), 'BLOCKED_TRIGGER_REFERENCE',
                'entry_execution.trigger_price_basis', 'La référence exacte du stop doit être précisée par le profil produit.')
    return profile


def price(rule, evaluator, at, instrument, normalize, field):
    raw = evaluator.value(rule['expression'], at)
    require(raw is not None, 'ORDER_PRICE_NOT_AVAILABLE', field, 'Le niveau n’est pas encore disponible à la décision.')
    raw = number(str(raw), field, positive=True)
    offset = number(rule['offset'], field + '.offset')
    delta = offset * Decimal(instrument['tick_size']) if rule['offset_unit'] == 'TICKS' else raw * offset / 100 if rule['offset_unit'] == 'PERCENT' else offset
    result = normalize(raw + delta, at, field)
    number(str(result), field, positive=True)
    return result


def expiry(order, lifecycle, signal_at, decision_at):
    tif = order['time_in_force']
    bounds = []
    session = lifecycle.calendar.containing(decision_at, close_inclusive=True)
    require(session is not None, 'ORDER_SESSION_MISSING', 'day.entry_order', 'Décision hors séance admissible.')
    if tif in ('AUTO', 'SESSION_END') or lifecycle.rules['overnight_policy'] == 'FORBID':
        bounds.append(session[1])
    if tif == 'GTD':
        until = stamp(order['good_till'])
        require(until > decision_at, 'ORDER_GTD_PAST', 'day.entry_order.good_till', 'Échéance postérieure à la soumission requise.')
        bounds.append(until)
    ttl = lifecycle.rules.get('signal_ttl')
    if ttl and ttl['mode'] == 'WALL_CLOCK': bounds.append(signal_at + timedelta(minutes=ttl['value']))
    # Eligible-session TTL is evaluated by DayLifecycle on the same session clock.
    for name in ('last_entry', 'force_flat'):
        bound = lifecycle.calendar.boundary(session, lifecycle.rules.get(name))
        if bound is not None: bounds.append(bound)
    return min(bounds) if bounds else None


def disclosure(order, profile):
    return dict(contract=clone(order), execution=clone(profile), **LIMITATIONS,
                sizing='KNOWN_SUBMISSION_REFERENCE_FIXED_QUANTITY',
                capacity='REJECT_WITHOUT_RESIZING', fill_time='QUOTE_TIME_OR_OHLC_AVAILABILITY_BOUND',
                scientific_trigger_distinct_from_order_trigger=True)
