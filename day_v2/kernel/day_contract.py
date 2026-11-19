"""Scientific DAY composition; no financial defaults and no executable text."""
from .contracts import keys, require, integer, digest
from .intraday_consolidation import DURATIONS
from .session_profiles import validate_boundary, validate_segments, SessionCalendar

VERSION = 'AURUM_DAY_METHODOLOGY_V1'


def validate(doc, check, requirements):
    d = doc.get('day')
    keys(d, ('version', 'signal_tf', 'session_profile_id', 'alignment', 'overnight_policy'), 'day',
         optional=('context_tf','trigger_tf','intrabar_tf','context_when','setup_when','approach_when',
                   'touch_when','trigger_when','confirmation_when','invalidation_when','signal_ttl',
                   'strategy_window','last_entry','force_flat','setup_family','entry_order'))
    require(d['version'] == VERSION, 'DAY_VERSION', 'day', 'Version DAY inconnue.')
    require(d['signal_tf'] == doc['timeframe'] and d['signal_tf'] in ('H4','H1','M30','M15','M10','M5'),
            'DAY_SIGNAL_TIMEFRAME', 'day.signal_tf', 'Timeframe DAY : H4, H1, M30, M15, M10 ou M5 ; M1 technique uniquement.')
    signal = d['signal_tf']; context = d.get('context_tf'); trigger = d.get('trigger_tf')
    require(context is None or (context in DURATIONS and DURATIONS[context] >= DURATIONS[signal]),
            'DAY_CONTEXT_TIMEFRAME', 'day.context_tf', 'Contexte égal ou supérieur au timeframe principal.')
    require(trigger is None or (trigger in ('H1','M30','M15','M10','M5') and DURATIONS[trigger] < DURATIONS[signal]),
            'DAY_TRIGGER_TIMEFRAME', 'day.trigger_tf', 'Le déclencheur supplémentaire doit être plus fin que le signal.')
    require(d.get('intrabar_tf') in (None, 'M1'), 'DAY_INTRABAR_TIMEFRAME', 'day.intrabar_tf', 'M1 facultatif uniquement pour ambiguïtés SL/TP.')
    require(isinstance(d['session_profile_id'], str) and bool(d['session_profile_id'].strip()),
            'DAY_SESSION_REQUIRED', 'day.session_profile_id', 'Sélectionner un profil de marché explicite.')
    require(d['alignment'] in ('CLOCK_ALIGNED','SESSION_ALIGNED'), 'DAY_ALIGNMENT', 'day.alignment', 'Alignement des barres requis.')
    require(d['overnight_policy'] in ('ALLOW','FORBID'), 'DAY_OVERNIGHT', 'day.overnight_policy', 'Choisir conservation ou interdiction overnight.')
    require((context is None) == (d.get('context_when') is None), 'DAY_CONTEXT_CONDITION', 'day.context_when', 'Un contexte ajouté doit posséder sa condition.')
    require((trigger is None) == (d.get('trigger_when') is None), 'DAY_TRIGGER_CONDITION', 'day.trigger_when', 'Un timeframe de trigger ajouté exige une condition explicite.')
    for name in ('approach_when','touch_when','confirmation_when'):
        require(d.get(name) is None or trigger is not None, 'DAY_TRIGGER_REQUIRED', 'day.' + name, 'Cette étape nécessite un déclencheur supplémentaire.')
    roles = {signal, context, trigger} - {None}
    for name in ('context_when','setup_when','approach_when','touch_when','trigger_when','confirmation_when','invalidation_when'):
        node = d.get(name)
        if node is None:
            continue
        info = check(node, 'day.' + name)
        allowed = {context} if name == 'context_when' else roles if name == 'invalidation_when' else {signal, context} - {None} if name == 'setup_when' else {trigger, signal, context} - {None}
        require(info.unit == 'BOOLEAN' and info.timeframes <= allowed, 'DAY_CONDITION_SCOPE', 'day.' + name, 'Condition booléenne limitée aux rôles de timeframes déclarés.')
        for tf in info.timeframes:
            requirements[tf] = max(requirements.get(tf, 0), info.warmup)
    if d.get('entry_order') is not None:
        from .order_contract import validate as validate_order
        validate_order(d['entry_order'], doc, check, requirements)
    require(set(requirements) <= roles, 'DAY_UNDECLARED_TIMEFRAME', 'day', 'Une série utilise un timeframe scientifique non déclaré ; M1 intrabar n’est pas un rôle scientifique.')
    entry = check(doc['entry']['when'], 'entry.when')
    require(entry.timeframes <= {signal, context} - {None}, 'DAY_ENTRY_SCOPE', 'entry.when', 'Le signal ne peut utiliser un trigger futur ; définir la condition de trigger séparément.')
    if doc['exit']['stop']:
        stop = check({'op':'ref','name':doc['exit']['stop']['series']}, 'exit.stop')
        require(stop.timeframes <= {signal, context} - {None}, 'DAY_STOP_SCOPE', 'exit.stop', 'Le stop initial est connu au signal, sans trigger futur.')
    ttl = d.get('signal_ttl')
    if ttl is not None:
        keys(ttl, ('value','unit','mode'), 'day.signal_ttl')
        integer(ttl['value'], 'day.signal_ttl.value', 1, 525600)
        require(ttl['unit'] == 'MINUTES' and ttl['mode'] in ('WALL_CLOCK','ELIGIBLE_SESSION_TIME'),
                'DAY_TTL_MODE', 'day.signal_ttl', 'TTL en minutes, murales ou admissibles en session.')
    if d.get('strategy_window') is not None:
        validate_segments(d['strategy_window'])
        require(bool(d['strategy_window']), 'DAY_EMPTY_WINDOW', 'day.strategy_window', 'Une fenêtre choisie ne peut être vide.')
    for field in ('last_entry','force_flat'):
        validate_boundary(d.get(field), 'day.' + field)
    require(d['overnight_policy'] != 'FORBID' or d.get('force_flat') is not None,
            'DAY_FORCE_FLAT_REQUIRED', 'day.force_flat', 'Overnight interdit : définir une échéance de liquidation avant fermeture.')
    if 'setup_family' in d:
        require(isinstance(d['setup_family'], str) and len(d['setup_family']) <= 80, 'DAY_SETUP_FAMILY', 'day.setup_family', 'Libellé descriptif court attendu, sans recette automatique.')
    for tf in roles:
        requirements[tf] = max(1, requirements.get(tf, 0))
    return dict(version=VERSION, execution_timeframe=trigger or signal, scientific_timeframes=sorted(roles),
                signal_tf=signal, context_tf=context, trigger_tf=trigger, intrabar_tf=d.get('intrabar_tf'),
                m1_role=('SCIENTIFIC_AND_INTRABAR' if d.get('intrabar_tf') == 'M1' else 'SCIENTIFIC') if 'M1' in roles
                else 'INTRABAR_ONLY' if d.get('intrabar_tf') == 'M1' else 'NOT_REQUESTED')


def configuration(plan, cfg):
    d = plan['definition']['day']
    profile = cfg.get('session_profile')
    require(isinstance(profile, dict), 'DAY_SESSION_PROFILE_MISSING', 'session_profile', 'Profil de marché absent ; aucun horaire supposé.')
    calendar = SessionCalendar(profile)
    if d.get('entry_order') is not None:
        from .order_contract import validate_execution
        validate_execution(cfg.get('entry_execution'), plan['definition']['asset'], d['entry_order'], cfg['instrument'])
        require(cfg.get('sizing',{}).get('determination') == 'ORDER_SUBMISSION_V1', 'ORDER_SIZING_TIME',
                'sizing.determination', 'Le nouveau contrat d’ordre fige sa quantité à la décision, sans future ouverture.')
    require(profile['id'] == d['session_profile_id'], 'DAY_SESSION_PROFILE_MISMATCH', 'session_profile', 'Le profil sélectionné diffère du plan.')
    require(cfg.get('data_acceptance', {}).get('opening_policy') == 'FIXED_BAR_BOUNDARY',
            'DAY_OPENING_POLICY', 'data_acceptance.opening_policy', 'DAY utilise l’ouverture de la prochaine barre du timeframe d’exécution.')
    from .contracts import stamp
    for session in calendar.intervals(stamp(cfg['period_start']), stamp(cfg['period_end'])):
        calendar.windows(session, d.get('strategy_window'))
        for name in ('last_entry','force_flat'):
            bound = calendar.boundary(session, d.get(name))
            require(bound is None or session[0] <= bound < session[1], 'DAY_SESSION_BOUNDARY_OUTSIDE',
                    'day.' + name, 'La limite doit se trouver dans la séance réellement applicable (y compris fermeture anticipée).')
    return calendar
