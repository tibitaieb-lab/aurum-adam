"""Scientific authoring requirements shared by presentation and command preflight.

V1: explicit personal-source declaration; no inferred author, citation or review.
Stored legacy fields and the native Hypothesis validator are not migrated.
"""
from .contracts import ContractError, integer, require, TIMEFRAMES

VERSION = 'AURUM_SCIENTIFIC_FIELDS_V1'
BUDGET_FIELDS = ('max_implementations','max_free_parameters','max_values_per_parameter',
                 'max_variants','max_assets','max_timeframes','max_total_runs')
REQUIRED_TEXT = ('title','initial_observation','primary_phenomenon','null_hypothesis_h0',
    'alternative_hypothesis_h1','entry_rules','exit_rules','baseline','success_criteria',
    'rejection_criteria','oos_policy','revision_policy','closure_condition')
SCOPE_FIELDS = ('assets','timeframes','direction')
ORIGINS = {'PERSONAL':'Idée personnelle','ARTICLE':'Article / étude','BOOK':'Livre','OTHER':'Autre'}
NATURES = {'EXPLORATORY':'Exploratoire','CONFIRMATORY':'Confirmatoire'}
MESSAGES = {
    'title':'Donnez un titre à votre hypothèse.',
    'initial_observation':'Décrivez votre observation ou l’idée à l’origine de cette hypothèse.',
    'primary_phenomenon':'Décrivez le phénomène principal que vous voulez étudier.',
    'null_hypothesis_h0':'Décrivez ce qui serait attendu en l’absence de l’effet recherché.',
    'alternative_hypothesis_h1':'Décrivez l’effet que cette hypothèse cherche à tester.',
    'entry_rules':'Précisez quand et comment entrer en position.',
    'exit_rules':'Précisez quand et comment sortir de position.',
    'baseline':'Indiquez la référence scientifique et sa justification.',
    'success_criteria':'Précisez la mesure, son unité et le seuil de succès.',
    'rejection_criteria':'Précisez le critère qui ne soutiendrait pas votre hypothèse.',
    'oos_policy':'Précisez la politique hors échantillon, sans présumer une indépendance.',
    'revision_policy':'Précisez comment seront traitées les modifications et nouvelles tentatives.',
    'closure_condition':'Précisez la condition de clôture de cette expérience.',
    'assets':'Indiquez l’actif à étudier.',
    'timeframes':'Indiquez le timeframe des signaux (M15, H1, H4 ou D1).',
    'direction':'Choisissez le sens LONG ou SHORT.',
}

def present(fields,key):
    return bool(fields.get(key,'').strip())

def field_status(key,fields):
    """Resolved status for the current case; does not assign any value."""
    from . import standard_authoring as standard
    if standard.enabled(fields):
        if key in standard.MANUAL:return 'REQUIRED'
        if key in standard.AUTO:return 'AUTO'
        if key in standard.DERIVED:return 'DERIVED'
    origin=fields.get('source_origin','')
    if key=='source_origin':
        return 'CONDITIONAL_REQUIRED' if not present(fields,'source_reference') else 'OPTIONAL'
    if key in ('source_reference','source_author','source_date'):
        if origin=='PERSONAL' or (not origin and not present(fields,'source_reference')):
            return 'NOT_APPLICABLE'
        return 'CONDITIONAL_REQUIRED' if key=='source_reference' else 'OPTIONAL'
    if key=='confirmatory':
        return 'OPTIONAL' if fields.get('scientific_nature','').strip()=='CONFIRMATORY' else 'NOT_APPLICABLE'
    if key in REQUIRED_TEXT or key in BUDGET_FIELDS or key in SCOPE_FIELDS or key=='scientific_nature':
        return 'REQUIRED'
    return 'OPTIONAL'

def parse_budget_value(fields,key):
    text=fields.get(key,'')
    require(type(text) is str and text.isascii() and text.isdigit(),'BUDGET_INTEGER_REQUIRED',key,
            'Renseignez un entier décimal explicite (0 est admis pour les paramètres libres).')
    try:value=int(text)
    except ValueError as exc:
        raise ContractError('INTEGER_RANGE',key,'Entier trop long ; maximum autorisé : 100000.') from exc
    return integer(value,key,0 if key=='max_free_parameters' else 1,100000)

def scientific_issues(fields):
    """Text/source/nature constraints; budget and plan keep their own validators."""
    from . import standard_authoring as standard
    if standard.enabled(fields):
        resolved=standard.resolve(fields);f=dict(resolved['fields']);f.pop(standard.MARKER,None)
        return resolved['issues']+scientific_issues(f)
    issues=[]
    def add(key,message,code='SCIENTIFIC_FIELD_REQUIRED'):
        issues.append(dict(code=code,field=key,message=message,status='BLOCK'))
    for key in REQUIRED_TEXT:
        if not present(fields,key):add(key,MESSAGES[key])
    origin=fields.get('source_origin','')
    if origin and origin not in ORIGINS:
        add('source_origin','Choisissez une origine parmi les quatre propositions.','SOURCE_ORIGIN_INVALID')
    if origin!='PERSONAL' and not present(fields,'source_reference'):
        if origin:add('source_reference','Indiquez une référence permettant de retrouver la source (titre, lien ou référence).')
        else:add('source_origin','Indiquez l’origine de l’idée ou conservez une référence de source explicite.')
    if fields.get('scientific_nature','').strip()!='EXPLORATORY':
        message=('Choisissez la nature de la recherche.' if not present(fields,'scientific_nature') else
            'Le protocole confirmatoire structuré n’est pas pris en charge ici. Le texte est conservé, mais la préparation pour exécution reste bloquée.')
        add('scientific_nature',message,'CONFIRMATORY_PROTOCOL_UNSUPPORTED')
    return issues

def field_errors(fields):
    from . import standard_authoring as standard
    if standard.enabled(fields):
        r=standard.resolve(fields);f=dict(r['fields']);f.pop(standard.MARKER,None)
        errors=field_errors(f)
        # A derived value is repaired at its author input, never with a ninth box.
        target={'primary_phenomenon':'initial_observation','direction':'entry_rules',
                'null_hypothesis_h0':'alternative_hypothesis_h1','baseline':'alternative_hypothesis_h1',
                'success_criteria':'alternative_hypothesis_h1','rejection_criteria':'alternative_hypothesis_h1'}
        errors={target.get(k,k):v for k,v in errors.items()}
        errors.update({i['field']:i['message'] for i in r['issues']})
        return errors
    errors={item['field']:item['message'] for item in scientific_issues(fields)}
    for key in BUDGET_FIELDS:
        try:parse_budget_value(fields,key)
        except ContractError as exc:errors[key]=exc.message
    for key in SCOPE_FIELDS:
        if not present(fields,key):errors[key]=MESSAGES[key]
    from .methodology import from_fields
    research=from_fields(fields)
    portfolio=research is not None and research.get('submode')=='PORTFOLIO'
    if present(fields,'timeframes') and fields['timeframes'].strip() not in TIMEFRAMES:
        errors['timeframes']='Choisissez un seul timeframe de signal pris en charge par la méthodologie.'
    if present(fields,'direction') and fields['direction'].strip() not in (('LONG','SHORT','BOTH') if portfolio else ('LONG','SHORT')):
        errors['direction']='Un seul sens LONG ou SHORT est pris en charge par définition mono-actif.'
    if len(fields.get('assets','').strip())>40 and not portfolio:
        errors['assets']='Identifiant instrument limité à 40 caractères.'
    h0=fields.get('null_hypothesis_h0','').strip()
    if h0 and h0.lower()==fields.get('alternative_hypothesis_h1','').strip().lower():
        errors['null_hypothesis_h0']='H0 et H1 doivent exprimer deux hypothèses distinctes.'
    if any(token in fields.get('primary_phenomenon','') for token in ('+',';','|')):
        errors['primary_phenomenon']='Le contrôle scientifique détecte plusieurs phénomènes possibles (+, ; ou |). Décrivez un phénomène principal.'
    return errors

def source_payload(fields,*,synthetic):
    """Only explicit PERSONAL converts observation into a traceable self-source."""
    origin=fields.get('source_origin','')
    if origin=='PERSONAL':
        if not present(fields,'initial_observation'):return None
        return dict(source_type='MARKET_OBSERVATION',source_reference=fields['initial_observation'],
                    source_author='',source_date='',source_summary=fields.get('source_summary',''),
                    source_confidence='EXAMPLE_ONLY' if synthetic else 'LOW')
    if not present(fields,'source_reference'):return None
    return dict(source_type='OTHER_JUSTIFIED',
                source_reference=fields['source_reference'],source_author=fields.get('source_author',''),
                source_date=fields.get('source_date',''),source_summary=fields.get('source_summary',''),
                source_confidence='EXAMPLE_ONLY' if synthetic else 'LOW')
