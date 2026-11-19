"""Explicit research identity, independent of the chosen bar frequency."""
from .contracts import keys, require, clone
VERSION='AURUM_METHODOLOGY_V1'
METHODS=('SWING','DAY','LONG_TERM')
SUBMODES=('SINGLE_ASSET','PORTFOLIO')
STATUSES=('DOCUMENTED','DERIVED','MODEL','ASSUMED','UNKNOWN','NOT_APPLICABLE')
RETURN_BASES=('PRICE_ONLY','TOTAL_RETURN','SPOT','CFD_PROXY','CONTINUOUS','OTHER','UNKNOWN','RAW','SPLIT_ADJUSTED','ADJUSTED','CONTINUOUS_FUTURE')


def validate(value,timeframe,*,portfolio_v2=False):
    keys(value,('version','methodology','submode','return_basis'),'research')
    require(value['version']==VERSION,'METHODOLOGY_VERSION','methodology','Version de méthodologie inconnue.')
    method=value['methodology'];mode=value['submode']
    require(method in METHODS and mode in SUBMODES and (method=='LONG_TERM' or mode=='SINGLE_ASSET'),
            'METHODOLOGY_REQUIRED','methodology','Choisir Swing, Day ou Long Term mono-actif ou portefeuille.')
    require(timeframe in (('W1','D1','H4','H1') if method=='SWING' else ('H4','H1','M30','M15','M10','M5') if method=='DAY' else ('D1','W1','MN1')),
            'METHODOLOGY_TIMEFRAME','timeframes','Timeframe incompatible avec la méthodologie choisie.')
    basis=value['return_basis']
    keys(basis,('basis','status','reference','dividend_status','corporate_action_status','roll_status','financing_status'),'return_basis')
    require(basis['basis'] in RETURN_BASES and basis['status'] in STATUSES,
            'RETURN_BASIS_INVALID','return_basis','Base et statut déclarés requis.')
    require(isinstance(basis['reference'],str) and bool(basis['reference'].strip()),'RETURN_BASIS_REFERENCE','return_basis','Provenance ou justification requise.')
    for k in ('dividend_status','corporate_action_status','roll_status','financing_status'):
        require(basis[k] in STATUSES,'RETURN_COMPONENT_STATUS','return_basis.'+k,'Statut de composante explicite requis.')
    require(basis['basis'] in (('PRICE_ONLY','SPOT','CFD_PROXY','RAW','SPLIT_ADJUSTED','ADJUSTED','TOTAL_RETURN','CONTINUOUS_FUTURE') if portfolio_v2 else ('PRICE_ONLY','SPOT','CFD_PROXY')), 'RETURN_BASIS_NOT_SUPPORTED','return_basis',
            'V1 ne calcule pas dividendes, corporate actions ni rolls : choisir une base compatible explicitement ou fournir une extension de capacité.')
    return value


def from_fields(fields):
    import json
    raw=fields.get('_research_identity')
    return None if raw is None else json.loads(raw)


def attach(definition,fields):
    identity=from_fields(fields)
    if identity is not None: definition['research']=clone(identity)
    if identity and identity['methodology']=='DAY':
        from .day_authoring import attach as attach_day
        attach_day(definition,fields)
    return definition


def identity(definition):
    return clone(definition.get('research') or {'version':VERSION,'methodology':'SWING','submode':'SINGLE_ASSET',
        'return_basis':None,'compatibility':'PRE_METHODOLOGY_V1_UNCHANGED'})


def label(value):
    if value['methodology']=='DAY':return 'DAY TRADING'
    return 'SWING / MEDIUM TERM' if value['methodology']=='SWING' else 'LONG TERM / PORTEFEUILLE' if value['submode']=='PORTFOLIO' else 'LONG TERM / ACTIF UNIQUE'
