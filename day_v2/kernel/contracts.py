"""Closed, bounded data contracts; expressions never contain executable text."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
import hashlib
import json
import re

from . import CONTRACT_VERSION, COMPILER_VERSION, ENGINE_VERSION

TIMEFRAMES = {'M1':60, 'M5':300, 'M10':600, 'M15':900, 'M30':1800, 'H1':3600, 'H4':14400, 'D1':86400, 'W1':None, 'MN1':None}
MAX_WINDOW = 10000
MAX_NODES = 256
MAX_DEPTH = 16
MAX_BARS = 100000  # Unchanged LT and FX limits.
MAX_SWING_DAY_BARS = 500000

def scientific_limit(plan):
    return MAX_SWING_DAY_BARS if plan['definition'].get('research',{}).get('methodology') in ('SWING','DAY') else MAX_BARS

def admit_series_count(plan,count):
    limit=scientific_limit(plan)
    require(0<count<=limit,'DATA_WINDOW_EMPTY_OR_TOO_LARGE','period',f'Aucune barre complète, ou plafond scientifique {limit} dépassé (amorçage inclus).')
    return limit

MAX_PAYLOAD = 1048576
IDENTIFIER = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,47}$')
PRIMITIVE_VERSION = '1.0.0'
SWING_SOURCE_V1 = 'PIVOT_HIGH_LOW_2_2_ON_OHLC'
PRIMITIVES = {
    'pivot_high': 'Dernier pivot haut confirmé après L/R observations, égalités exclues',
    'pivot_low': 'Dernier pivot bas confirmé après L/R observations, égalités exclues',
    'field': 'OHLC : prix ; volume : quantité déclarée ; barre clôturée uniquement',
    'constant': 'Constante finie avec unité PRICE, RATIO, VOLUME ou BOOLEAN',
    'ref': 'Référence à une série nommée ; cycles interdits',
    'lag': 'Décalage passé entier de 0 à 10000 observations',
    'sma': 'Moyenne simple, fenêtre complète, pas de NaN ignoré',
    'ema': 'EMA close 8/20/50/200 ; alpha=2/(n+1), premiere cloture seed, adjust=False, min_periods=n',
    'atr': 'ATR14 ; TR0=high-low puis max(high-low, abs(high-prev_close), abs(low-prev_close)); alpha=1/14, premier TR seed, min_periods=14',
    'donchian_upper': 'highest(high,n).lag(1), n=20/40',
    'donchian_lower': 'lowest(low,n).lag(1), n=20/40',
    'donchian_middle': 'midpoint of previous-window upper/lower, n=20/40',
    'fractal_high': 'Strict five-bar high pivot, known two closed bars after centre',
    'fractal_low': 'Strict five-bar low pivot, known two closed bars after centre',
    'macd_line': 'EMA12(close)-EMA26(close), AURUM first-close seed; visible after 26 bars',
    'macd_signal': 'EMA9 of MACD line, first valid line seed; visible after 34 bars',
    'macd_histogram': 'MACD line minus signal; visible after 34 bars',
    'rsi': 'RSI14 Wilder; SMA seed over 14 changes; flat 0/0 unavailable; one-sided limits 0 or 100',
    'stochastic_k': 'Slow K14/3/3: SMA3 of raw 100*(close-LL14)/(HH14-LL14); zero span unavailable',
    'stochastic_d': 'Slow D14/3/3: SMA3 of slow K; zero span unavailable',
    'stoch_rsi_k': 'RSI14 then stochastic window14, SMA3 raw; zero RSI span unavailable',
    'stoch_rsi_d': 'RSI14 then stochastic window14, SMA3 raw and SMA3 K; zero RSI span unavailable',
    'plus_di': '+DI14 Wilder smoothed TR/+DM sums; zero smoothed TR unavailable',
    'minus_di': '-DI14 Wilder smoothed TR/-DM sums; zero smoothed TR unavailable',
    'adx': 'ADX14 Wilder; first 14 consecutive valid DX mean, then Wilder recurrence; zero denominators unavailable',
    'ichimoku_tenkan': 'Midpoint of highest high / lowest low in current 9-bar window',
    'ichimoku_kijun': 'Midpoint of highest high / lowest low in current 26-bar window',
    'ichimoku_senkou_a': 'Current calculated midpoint of Tenkan and Kijun; display offset excluded',
    'ichimoku_senkou_b': 'Midpoint of highest high / lowest low in current 52-bar window; display offset excluded',
    'range': 'high-low, closed bar',
    'body': 'abs(close-open), closed bar',
    'upper_wick': 'high-max(open,close), closed bar',
    'lower_wick': 'min(open,close)-low, closed bar',
    'body_ratio': 'body/range; zero range unavailable',
    'close_location': '(close-low)/range; zero range unavailable',
    'bullish_candle': 'close>open',
    'bearish_candle': 'close<open',
    'inside_bar': 'high<previous high AND low>previous low',
    'outside_bar': 'high>previous high AND low<previous low',
    'bullish_engulfing': 'previous bearish, current bullish, open<=previous close, close>=previous open',
    'bearish_engulfing': 'previous bullish, current bearish, open>=previous close, close<=previous open',
    'gap_size': 'open-previous close',
    'gap_up': 'open>previous close',
    'gap_down': 'open<previous close',
    'nr4': 'current range equals minimum of four complete ranges; ties included',
    'nr7': 'current range equals minimum of seven complete ranges; ties included',
    'range_expansion': 'current range>SMA(range,20)',
    'range_contraction': 'current range<SMA(range,20)',
    'breakout_up': 'Close crossing strictly above explicit causal resistance level on this closed bar',
    'breakout_down': 'Close crossing strictly below explicit causal support level on this closed bar',
    'false_breakout_up': 'Current high strictly exceeds resistance then close <= resistance on same closed bar',
    'false_breakout_down': 'Current low strictly breaches support then close >= support on same closed bar',
    'higher_high': 'Last two confirmed pivot highs (OHLC high, left/right 2/2) form persistent strict higher state',
    'higher_low': 'Last two confirmed pivot lows (OHLC low, left/right 2/2) form persistent strict higher state',
    'lower_high': 'Last two confirmed pivot highs (OHLC high, left/right 2/2) form persistent strict lower state',
    'lower_low': 'Last two confirmed pivot lows (OHLC low, left/right 2/2) form persistent strict lower state',
    'break_of_structure_up': 'Previous close <= pivot high available at t-1; current close > same pivot high',
    'break_of_structure_down': 'Previous close >= pivot low available at t-1; current close < same pivot low',
    'highest': 'Maximum de fenêtre complète ; lag=1 pour exclure la barre courante',
    'lowest': 'Minimum de fenêtre complète ; lag=1 pour exclure la barre courante',
    'return': 'Rendement simple x[t]/x[t-n] - 1, sans annualisation ni taux sans risque',
    'add': 'Addition, unités identiques', 'sub': 'Soustraction, unités identiques',
    'mul': 'Produit par un ratio sans dimension', 'div': 'Ratio unités identiques ou division par ratio ; zéro -> indisponible',
    'gt': '>', 'ge': '>=', 'lt': '<', 'le': '<=', 'eq': '==',
    'cross_above': 'A précédent <= B précédent puis A courant > B courant',
    'cross_below': 'A précédent >= B précédent puis A courant < B courant',
    'all': 'Toutes les conditions ; valeur manquante -> indisponible',
    'any': 'Au moins une condition ; valeur manquante -> indisponible',
    'not': 'Négation ; indisponible ne devient jamais vrai',
}


class ContractError(ValueError):
    def __init__(self, code, field, message):
        self.code, self.field, self.message = code, field, message
        super().__init__(f'{code} · {field} : {message}')

    def as_dict(self):
        return {'code':self.code, 'field':self.field, 'message':self.message, 'status':'BLOCK'}


def require(condition, code, field, message):
    if not condition:
        raise ContractError(code, field, message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def clone(value):
    try:
        text = canonical(value)
        require(len(text.encode('utf-8')) <= MAX_PAYLOAD, 'PAYLOAD_TOO_LARGE', 'definition', 'Limite de 1 Mio dépassée.')
        return json.loads(text)
    except (TypeError, ValueError, RecursionError) as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError('INVALID_JSON_DATA', 'definition', 'Objet de données JSON fini requis.') from exc


def number(value, field, *, positive=False, nonnegative=False):
    require(value is not None and not (isinstance(value,str) and not value.strip()),
            'VALUE_REQUIRED', field, 'Valeur à renseigner ; zéro doit être choisi explicitement.')
    require(type(value) in (str, int), 'DECIMAL_REQUIRED', field, 'Nombre décimal explicite requis, sans booléen ni flottant binaire.')
    require(len(str(value)) <= 80, 'NUMBER_TOO_LONG', field, 'Nombre trop long.')
    text=str(value).strip().replace('\u00a0',' ').replace('\u202f',' ')
    # Comma is decimal, never a thousands separator. Grouping uses spaces only.
    require(bool(re.fullmatch(r'[+-]?(?:[0-9]+|[0-9]{1,3}(?: [0-9]{3})+)(?:[.,][0-9]+)?(?:[eE][+-]?[0-9]+)?',text)),
            'DECIMAL_FORMAT',field,'Format : 10000,50 ou 10 000,50 ou 10000.50 ; ne pas mélanger virgule et point. La virgule est toujours décimale.')
    try:
        result = Decimal(text.replace(' ','').replace(',','.'))
    except InvalidOperation as exc:
        raise ContractError('DECIMAL_REQUIRED', field, 'Nombre décimal invalide.') from exc
    require(result.is_finite() and abs(result) <= Decimal('1e30') and result.as_tuple().exponent >= -24,
            'NONFINITE_OR_EXCESS_PRECISION', field, 'Nombre fini, amplitude <= 10^30 et au plus 24 décimales requis.')
    require(not positive or result > 0, 'POSITIVE_REQUIRED', field, 'Valeur strictement positive requise.')
    require(not nonnegative or result >= 0, 'NONNEGATIVE_REQUIRED', field, 'Valeur positive ou nulle requise.')
    return result


def integer(value, field, minimum=0, maximum=MAX_WINDOW):
    require(type(value) is int and minimum <= value <= maximum, 'INTEGER_RANGE', field,
            f'Entier entre {minimum} et {maximum} requis.')
    return value


def keys(value, required, field, optional=()):
    require(type(value) is dict, 'OBJECT_REQUIRED', field, 'Objet structuré requis.')
    require(set(required) <= set(value) and set(value) <= set(required) | set(optional),
            'CLOSED_SCHEMA', field, f'Champs attendus : {", ".join(required)} ; champs supplémentaires refusés.')


def stamp(value, field='time'):
    require(type(value) is str, 'TIME_REQUIRED', field, 'Horodatage avec fuseau requis.')
    try:
        parsed = datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError as exc:
        raise ContractError('TIME_INVALID', field, 'Horodatage ISO invalide.') from exc
    require(parsed.tzinfo is not None, 'TIMEZONE_REQUIRED', field, 'Fuseau explicite requis.')
    return parsed.astimezone(timezone.utc)


def iso(value):
    return value.astimezone(timezone.utc).isoformat()


def capabilities():
    toolbox_ops={
        'ema','atr','donchian_upper','donchian_lower','donchian_middle',
        'macd_line','macd_signal','macd_histogram','ichimoku_tenkan','ichimoku_kijun',
        'ichimoku_senkou_a','ichimoku_senkou_b','fractal_high','fractal_low',
        'range','body','upper_wick','lower_wick','body_ratio','close_location',
        'bullish_candle','bearish_candle','inside_bar','outside_bar',
        'bullish_engulfing','bearish_engulfing','gap_size','gap_up','gap_down',
        'nr4','nr7','range_expansion','range_contraction',
        'rsi','stochastic_k','stochastic_d','stoch_rsi_k','stoch_rsi_d',
        'plus_di','minus_di','adx','breakout_up','breakout_down',
        'false_breakout_up','false_breakout_down','higher_high','higher_low',
        'lower_high','lower_low','break_of_structure_up','break_of_structure_down'}
    boolean_ops={'bullish_candle','bearish_candle','inside_bar','outside_bar',
        'bullish_engulfing','bearish_engulfing','gap_up','gap_down','nr4','nr7',
        'range_expansion','range_contraction','breakout_up','breakout_down',
        'false_breakout_up','false_breakout_down','higher_high','higher_low',
        'lower_high','lower_low','break_of_structure_up','break_of_structure_down'}
    ratio_ops={'body_ratio','close_location','rsi','stochastic_k','stochastic_d',
        'stoch_rsi_k','stoch_rsi_d','plus_di','minus_di','adx'}
    def specification(op):
        if op=='ema':params={'periods':[8,20,50,200]};warmup='periods';seed='first close'
        elif op=='atr':params={'periods':[14]};warmup=14;seed='first true range'
        elif op.startswith('donchian_'):params={'periods':[20,40]};warmup='periods+1';seed='complete prior window'
        elif op.startswith('macd_'):params={'fast':12,'slow':26,'signal':9};warmup=26 if op=='macd_line' else 34;seed='AURUM first-close EMA; signal first valid line'
        elif op.startswith('ichimoku_'):params={'tenkan':9,'kijun':26,'senkou_b':52};warmup=9 if op=='ichimoku_tenkan' else 52 if op=='ichimoku_senkou_b' else 26;seed='complete current window'
        elif op.startswith('fractal_'):params={'left':2,'right':2};warmup=5;seed='confirmed at centre+2'
        elif op in ('nr4','nr7'):params={'window':4 if op=='nr4' else 7};warmup=params['window'];seed='complete window; equality included'
        elif op in ('range_expansion','range_contraction'):params={'window':20};warmup=20;seed='complete SMA window'
        elif op in ratio_ops and op not in ('body_ratio','close_location'):
            params=({'rsi':14} if op=='rsi' else {'stochastic':[14,3,3]} if op.startswith('stochastic_') else
                    {'stochastic_rsi':[14,14,3,3]} if op.startswith('stoch_rsi_') else {'wilder':14})
            warmup={'rsi':15,'stochastic_k':16,'stochastic_d':18,'stoch_rsi_k':30,
                    'stoch_rsi_d':32,'plus_di':15,'minus_di':15,'adx':28}[op]
            seed='Mission V1 explicit SMA/Wilder seed; zero denominator unavailable'
        elif op in ('breakout_up','breakout_down','false_breakout_up','false_breakout_down'):
            params={'level_series':'explicit prior extrema, Donchian, confirmed pivot or fractal'}
            warmup='level+1' if op.startswith('breakout_') else 'level'
            seed='closed-bar event; strict penetration, equality rules in formula'
        elif op in ('higher_high','higher_low','lower_high','lower_low',
                    'break_of_structure_up','break_of_structure_down'):
            params={'swing_source':SWING_SOURCE_V1}
            warmup=6 if op.startswith('break_of_structure_') else 8
            seed='confirmed pivot 2/2, available at centre+2'
        else:params={};warmup=2 if op in ('inside_bar','outside_bar','bullish_engulfing','bearish_engulfing','gap_size','gap_up','gap_down') else 1;seed='none'
        source=('AURUM_EXISTING_CONTRACT' if op in ('ema','atr') else
                'USER_MISSION_CLOSE18_CONTRACT' if op in {'rsi','stochastic_k','stochastic_d','stoch_rsi_k','stoch_rsi_d','plus_di','minus_di','adx','breakout_up','breakout_down','false_breakout_up','false_breakout_down','higher_high','higher_low','lower_high','lower_low','break_of_structure_up','break_of_structure_down'} else
                'USER_MISSION_CONTRACT' if op not in ('macd_line','macd_signal','macd_histogram','ichimoku_tenkan','ichimoku_kijun','ichimoku_senkou_a','ichimoku_senkou_b') else
                'TA_LIB_FORMULA_WITH_AURUM_EMA_SEED' if op.startswith('macd_') else 'TRADITIONAL_ICHIMOKU_CAUSAL_VALUES')
        return {'supported':True,'parameters':params,'formula':PRIMITIVES[op],
            'inputs':['close'] if op in ('ema','rsi','stoch_rsi_k','stoch_rsi_d') or op.startswith('macd_') else
                ['explicit_causal_level','close'] if op.startswith('breakout_') or op.startswith('false_breakout_') else
                ['confirmed_pivot_high_low_2_2','close'] if op in ('higher_high','higher_low','lower_high','lower_low','break_of_structure_up','break_of_structure_down') else
                ['high','low','close'] if op in ('stochastic_k','stochastic_d','plus_di','minus_di','adx') else ['open','high','low','close'],
            'output_type':'BOOLEAN' if op in boolean_ops else 'RATIO' if op in ratio_ops else 'PRICE',
            'warmup':warmup,'seed':seed,'causality':'CLOSED_BARS_AS_OF_DECISION',
            'limitations':'No future display shift; missing required data -> unavailable',
            'supported_compositions':['ref','lag','sma','highest','lowest','comparison','arithmetic_by_unit'],
            'formula_provenance':source}
    return {'contract':CONTRACT_VERSION,'compiler':COMPILER_VERSION,'engine':ENGINE_VERSION,
            'technical_toolbox_v1':{'status':'DONE','swing_source_v1':SWING_SOURCE_V1,
                'supported':{op:specification(op) for op in sorted(toolbox_ops)},'blocked':[]},
            'primitives':{k:{'version':PRIMITIVE_VERSION,'convention':v} for k,v in PRIMITIVES.items()},
            'timeframes':TIMEFRAMES,'directions':['LONG','SHORT'], 'mode':['DIRECT'],
            'entry':['NEXT_BAR_OPEN','DECLARED_ORDER_DAY_V1'], 'exits':['FIXED_STOP','FIXED_TARGET_R','CONDITION_NEXT_OPEN','EXPLICIT_MAX_BARS'],
            'sizing':['FIXED_UNITS','RISK_PERCENT_INITIAL_CAPITAL','RISK_PERCENT_EQUITY','TARGET_EXPOSURE_EQUITY','PORTFOLIO_TARGET_WEIGHTS'],
            'day':{'contract':'AURUM_DAY_METHODOLOGY_V1','order_contract':'AURUM_ENTRY_ORDER_V1','orders':['MARKET','LIMIT','STOP','STOP_LIMIT'],'sizing':'ORDER_SUBMISSION_V1','sessions':'EXPLICIT_VERSIONED_PROFILE_REQUIRED','recovery':'EXPLICIT_OUTSIDE_REPLAY_FROZEN_TICKS','partial_fills':'NOT_IMPLEMENTED','queue':'NOT_MODELED','market_impact':'NOT_MODELED'},
            'methodology':{'DAY':['H1','M15','M5','M1'],'SWING':['H1','H4','D1'],'LONG_TERM':['D1','W1','MN1'],'legacy_timeframes':['M15']},
            'portfolio':{'contract':'AURUM_PORTFOLIO_DEFINITION_V2','compatible_contracts':['AURUM_PORTFOLIO_DEFINITION_V1'],'allocation':['TARGET_WEIGHTS','EQUAL_WEIGHT','SCORE_WEIGHTED','MINIMUM_VARIANCE','MEAN_VARIANCE','MAXIMUM_SHARPE','RISK_PARITY','BLACK_LITTERMAN'],
                'rebalance':['WEEKLY','MONTHLY'],'account':'SHARED_RESEARCH_ACCOUNT','fills':'NEXT_OWN_OBSERVED_OPEN',
                'risk':'EXPLICIT_GLOBAL_CONSTRAINTS_AND_SAMPLE_COVARIANCE','open_policy':'MARK_OPEN_NO_LIQUIDATION','construction':'AURUM_PORTFOLIO_CONSTRUCTION_V2','optimizer':'SCIPY_SLSQP_EXPLICIT_INPUTS','cash':['AUTO_CONVERT_AT_FILL','MULTI_CURRENCY_CASHBOOK'],'normalization':['RAW','PRICE_ONLY','SPLIT_ADJUSTED','ADJUSTED','TOTAL_RETURN','SPOT','CFD_PROXY','CONTINUOUS_FUTURE'],'data_requirement':'RAW_EXECUTION_WITH_EXPLICIT_CORPORATE_ACTIONS_OR_ACTUAL_MAPPED_FUTURE_CONTRACTS'},
            'calendar':{'contract':'AURUM_CALENDAR_PERIOD_V1','source':'D1','timeframes':['W1','MN1'],'calendar':'EXPLICIT_IANA_ANCHOR','partial_periods':'EXCLUDED'},
            'execution':['LINEAR_QUOTE_CURRENCY_V1','LINEAR_ACCOUNT_V2'],
            'account':['CASH_ASSET_LONG','MARGIN_LINEAR'],
            'fx':['DATED_OBSERVATIONS_DIRECT_OR_INVERSE','CLOSED_DATASET_ASOF_WITH_STALENESS','CAUSAL_MULTI_HOP_EXPLICIT_ROUTE_V2'],
            'opening_time':['FIXED_BAR_BOUNDARY','FIRST_OBSERVED_M1_OPEN','BAR_OPEN_TIMESTAMP_V1'],
            'data_conventions':['DOCUMENTED_DECLARATION','AURUM_DATA_ASSUMPTIONS_V1_EXPLICIT_FILE_BOUND_ACCEPTANCE'],
            'm1_availability':{'open':'MINUTE_START','ohlc_complete':'MINUTE_END'},
            'bar_phase':'EXPLICIT_PER_DATASET_AND_TIMEFRAME_NO_ASSET_DEFAULT',
            'price_domain':'STRICTLY_POSITIVE_LINEAR_PRODUCTS_ONLY',
            'profiles':['VERSIONED_WORKING_INSTRUMENT','COSTS','DATA','ACCOUNT_SIZING','FX'],
            'intrabar':['DIRECT_M1_STOP_LAST_V1'],
            'end_of_period':['INCONCLUSIVE_IF_OPEN','CLOSED_ONLY'],
            'limits':{'nodes':MAX_NODES,'depth':MAX_DEPTH,'window':MAX_WINDOW,'bars':MAX_BARS,'bars_SWING_DAY':MAX_SWING_DAY_BARS},
            'unsupported':['texte libre exécutable','nouveaux ordres limit/stop hors du contrat DAY V1','pyramiding de signaux mono-actif',
                'options et futures sans contrats réels ou mapping explicite','produits autorisant des prix nuls ou négatifs','sizing par volatilité','promotion scientifique automatique',
                'agents/factors externes opérationnels','TOTAL_RETURN sans composantes documentées ou synthétiques explicites'],
            'migration':'Règles V1 ; économie V1 conservée pour anciens instantanés, activation explicite V2 sans inventer les choix manquants. Nouveaux dossiers V2. Versions inconnues refusées.'}


@dataclass(frozen=True)
class TypeInfo:
    unit: str
    warmup: int
    timeframes: frozenset
