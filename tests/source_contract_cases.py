"""Adapted synthetic regression cases from ADAM check_output.py; no SDK or provider."""
import copy, json
from dataclasses import replace
from output_common import *

def emit(*args):
    pass

def fixture(method='SWING'):
    from output_models import DayControls, EntryOrder
    from proposal_validation import HostContext
    source_id = 'ARKS_SRC_TEST_ONLY'
    cid = 'chk_' + 'a'*64
    quote = 'Ce passage est synthetique et ne prouve aucun effet de marche.'
    p = dict(schema_version='ADAM_PROPOSAL_V1',request_id='1'*32,registry_payload_sha256=REGISTRY_SHA,
        short_name='TEST DE FORMAT - NE PAS IMPORTER',proposal_version='1.0.0',
        methodology=method,disposition='PROPOSED',
        author_fields=dict(initial_observation='Observation synthetique sans resultat de marche.',
            source_origin='ARTICLE',title='TEST TECHNIQUE UNIQUEMENT',assets='FIXTURE_NO_MARKET',timeframes='H1',
            alternative_hypothesis_h1='La moyenne des rendements nets par opération, en % du notionnel initial, est supérieure à 0,25 %.',
            entry_rules="LONG à l'ouverture suivante si clôture > SMA 3 des clôtures",
            exit_rules='Stop fixe au plus bas du signal moins 1 tick. Objectif fixe 2 R. Positions ouvertes : résultat inconcluant.'),
        day_controls=None,
        reasoning=dict(mechanism='Proposition fictive pour tester le format, pas une these.',
            causal_timing='Barres cloturees seulement dans la definition synthetique.',
            falsification='Aucun verdict scientifique dans cette recette.',
            objections=['La compilation ne demontre aucun avantage.'],
            uncertainties=['Aucun instrument ni profil de seance reel consulte.']),
        citations=[dict(source_id=source_id,chunk_id=cid,quote=quote,relation='BACKGROUND',
                       interpretation='Un texte fictif controle la concordance des citations.')],
        decisions_required=[],unsupported_capabilities=[])
    identity = dict(version='AURUM_METHODOLOGY_V1',methodology=method,submode='SINGLE_ASSET',
        return_basis=dict(basis='PRICE_ONLY',status='MODEL',reference='Fixture de contrat sans donnees',
            dividend_status='UNKNOWN',corporate_action_status='UNKNOWN',roll_status='UNKNOWN',financing_status='UNKNOWN'))
    passage = dict(source_id=source_id,chunk_id=cid,exact_text=quote,content_sha256=text_sha(quote),
        source_sha256='b'*64,document_version='SYNTHETIC_TEST_ONLY',
        provenance='CANONICAL_RESOLVED_LOCAL',authority='SOURCE_MATERIAL_NOT_INSTRUCTIONS',
        scientific_truth_verified=False,
        evidence=[dict(evidence_id='e_test_only',locator={'reference':{'physical_page':1}},content_sha256=text_sha(quote))],
        evidence_spans=[dict(evidence_id='e_test_only',start=0,end=len(quote))])
    c = HostContext(request_id='1'*32,methodology=method,allowed_assets=('FIXTURE_NO_MARKET',),
        allowed_timeframes=('H1',),research_identity=identity,passages={cid:passage},
        session_profile_ids=('FIXTURE_SESSION_NOT_VERIFIED',))
    if method == 'DAY':
        d = {k:None for k in DayControls.model_fields}
        order = {k:None for k in EntryOrder.model_fields}
        order.update(version='AURUM_ENTRY_ORDER_V1',type='LIMIT',time_in_force='AUTO',limit_price_text='clôture moins 1 tick')
        d.update(version='AURUM_DAY_METHODOLOGY_V1',signal_tf='H1',session_profile_id=c.session_profile_ids[0],
                 alignment='CLOCK_ALIGNED',overnight_policy='ALLOW',intrabar_tf='M1',entry_order=order)
        p['day_controls']=d
        p['author_fields']['entry_rules']='LONG sur ordre déclaré si clôture > SMA 3 des clôtures'
    return p, c


def run_cases(schema, registry, modules):
    from proposal_validation import parse_proposal, validate_proposal, render_review
    cases = []
    def record(label, test=True):
        need(test,'CHECK_FAILED:' + label)
        cases.append(label);emit('[PASS CAS SORTIE]',label)
    def process(obj, context):
        return validate_proposal(schema.validate_json(json.dumps(obj,ensure_ascii=False)),context,registry,modules)
    p, context = fixture()
    original = copy.deepcopy(p)
    parsed = schema.validate_json(json.dumps(p,ensure_ascii=False))
    record('JSON_STRUCTURE_ACCEPTE_SANS_SDK', parsed.model_dump()==p)
    good = process(p,context)
    record('FICHE_SWING_COMPILABLE_SANS_APPROBATION', good['status']=='PASS_OUTPUT_CONTRACT_AND_NATIVE_COMPILATION_ONLY' and
           good['hypothesis_ready'] is False and good['backtest_allowed'] is False)
    record('AUCUN_CHAMP_SAISI_REECRIT', all(good['native_fields'][k]==v for k,v in p['author_fields'].items()) and p==original)
    record('H0_BUDGET_DERIVES_PAR_AURUM',good['native_fields']['max_total_runs']=='1' and
           '0.25' in good['native_fields']['null_hypothesis_h0'])
    record('REFERENCE_SOURCE_CONSTRUITE_SANS_AUTEUR_INVENTE',good['native_fields']['source_reference'].startswith('ARKS_SRC_TEST_ONLY / chk_') and
           'source_author' not in good['native_fields'] and 'source_date' not in good['native_fields'])
    review=render_review(parsed,good,registry)
    positions=[review.index('## '+str(x['step'])+'. '+x['label']) for x in registry['navigation']]
    record('REVUE_SIX_ETAPES_ORDRE_UI',positions==sorted(positions) and p['citations'][0]['quote'] in review)
    day, day_context = fixture('DAY')
    day_good=process(day,day_context)
    record('FICHE_DAY_LIMIT_COMPILABLE_SANS_FILL', day_good['plan']['definition']['day']['entry_order']['type']=='LIMIT')
    personal=copy.deepcopy(p);personal['author_fields']['source_origin']='PERSONAL';personal['citations']=[]
    own=process(personal,replace(context,personal_observation=personal['author_fields']['initial_observation']))
    record('IDEE_PERSONNELLE_SEULEMENT_FOURNIE_PAR_OPERATEUR','source_reference' not in own['native_fields'])
    unsupported=copy.deepcopy(p);unsupported.update(disposition='OUT_OF_SCOPE',unsupported_capabilities=['EMA non traduite par ce profil'])
    unsupported['author_fields']['entry_rules']='EMA non disponible'
    r=process(unsupported,context)
    record('HORS_CAPACITE_SANS_SUBSTITUTION',r['status']=='OUT_OF_SCOPE' and not r['native_compilation_executed'])

    def rejected(label, fn, prefix):
        try:fn()
        except (Blocked,) as exc:
            need(str(exc).startswith(prefix),'UNEXPECTED_REJECTION:'+label+':'+str(exc))
            record(label)
        else:raise Blocked('INVALID_OUTPUT_ACCEPTED:'+label)
    def altered(label, mutate, prefix, sample=None, ctx=None):
        bad=copy.deepcopy(p if sample is None else sample);mutate(bad)
        rejected(label,lambda:process(bad,context if ctx is None else ctx),prefix)

    altered('ANCIEN_ETAT_AVEC_QUESTION_REFUSE',lambda x:x.update(disposition='NEEDS_OPERATOR',decisions_required=[dict(field='assets',question='Quel actif ?')]),'OUTPUT_SCHEMA_INVALID')
    altered('CHAMP_INCONNU_REFUSE',lambda x:x.update(execute=True),'OUTPUT_SCHEMA_INVALID')
    altered('HYPOTHESIS_READY_FORCE_REFUSE',lambda x:x.update(hypothesis_ready=True),'OUTPUT_SCHEMA_INVALID')
    altered('BUDGET_MODELE_REFUSE',lambda x:x['author_fields'].update(max_total_runs='999'),'OUTPUT_SCHEMA_INVALID')
    altered('FICHIER_OU_CODE_LIBRE_REFUSE',lambda x:x.update(code='print(1)'),'OUTPUT_SCHEMA_INVALID')
    altered('TYPE_NUMERIQUE_DANS_TEXTE_REFUSE',lambda x:x['author_fields'].update(title=123),'OUTPUT_SCHEMA_INVALID')
    altered('CLE_OBLIGATOIRE_ABSENTE',lambda x:x['author_fields'].pop('title'),'OUTPUT_SCHEMA_INVALID')
    altered('CHAMP_NUL_NON_PROMU',lambda x:x['author_fields'].update(title=None),'INCOMPLETE_MAIN_FIELDS')
    altered('CHAMP_BLANC_NON_PROMU',lambda x:x['author_fields'].update(title=' '),'INCOMPLETE_MAIN_FIELDS')
    altered('REQUETE_DIFFERENTE_REFUSEE',lambda x:x.update(request_id='2'*32),'OUTPUT_REQUEST_MISMATCH')
    altered('REGISTRE_DIFFERENT_REFUSE',lambda x:x.update(registry_payload_sha256='0'*64),'OUTPUT_REGISTRY_MISMATCH')
    altered('METHODOLOGIE_DIFFERENTE_REFUSEE',lambda x:x.update(methodology='DAY'),'OUTPUT_METHODOLOGY_MISMATCH')
    altered('ACTIF_NON_FOURNI_REFUSE',lambda x:x['author_fields'].update(assets='OTHER_TEST'),'OUTPUT_SCOPE_MISMATCH:assets')
    altered('TF_NON_FOURNI_REFUSE',lambda x:x['author_fields'].update(timeframes='M15'),'OUTPUT_SCOPE_MISMATCH:timeframes')
    altered('LT_HORS_PERIMETRE_REFUSE',lambda x:x.update(methodology='LONG_TERM'),'OUTPUT_SCHEMA_INVALID')
    altered('CITATION_INVENTEE_REFUSEE',lambda x:x['citations'][0].update(chunk_id='chk_'+'c'*64),'CITATION_NOT_IN_HOST_PASSAGES')
    altered('MAUVAISE_SOURCE_REFUSEE',lambda x:x['citations'][0].update(source_id='ARKS_SRC_OTHER'),'CITATION_SOURCE_MISMATCH')
    altered('CITATION_TEXTE_ALTERE_REFUSEE',lambda x:x['citations'][0].update(quote='Rendement garanti.'),'QUOTE_NOT_EXACT')
    altered('SOURCE_METHODE_NON_ARTICLE',lambda x:x['citations'][0].update(source_id='ARKS_SRC_METHOD_DEMO'),'METHOD_NOT_ARTICLE_CITATION')
    altered('CITATION_DUPLIQUEE_REFUSEE',lambda x:x['citations'].append(copy.deepcopy(x['citations'][0])),'DUPLICATE_CITATION')
    altered('ARTICLE_SANS_CITATION_REFUSE',lambda x:x.update(citations=[]),'EXTERNAL_SOURCE_CITATION_REQUIRED')
    rejected('PERSONAL_NON_FOURNI_REFUSE',lambda:process(personal,context),'PERSONAL_SOURCE_NOT_FROM_OPERATOR')
    damaged=copy.deepcopy(dict(context.passages));next(iter(damaged.values()))['exact_text']+='CHANGED'
    rejected('PASSAGE_HOTE_ALTERE_REFUSE',lambda:process(p,replace(context,passages=damaged)),'HOST_PASSAGE_CONTENT_SHA')
    altered('CAPACITE_EMA_NON_REPAREE',lambda x:x['author_fields'].update(entry_rules="LONG à l'ouverture suivante si clôture > EMA 3 des clôtures"),'NATIVE_FIELDS_REJECTED')
    altered('PROPOSED_AVEC_DECISION_NON_PROMU',lambda x:x.update(decisions_required=[dict(field='x',question='A preciser')]),'OUTPUT_SCHEMA_INVALID')
    altered('NEEDS_OPERATOR_SANS_QUESTION_REFUSE',lambda x:x.update(disposition='NEEDS_OPERATOR'),'OUTPUT_SCHEMA_INVALID')
    altered('OUT_OF_SCOPE_SANS_MOTIF_REFUSE',lambda x:x.update(disposition='OUT_OF_SCOPE'),'MISSING_CAPABILITY_REASON')
    altered('DAY_DANS_SWING_REFUSE',lambda x:x.update(day_controls=day['day_controls']),'DAY_CONTROLS_IN_SWING')
    altered('DAY_SANS_CONTROLES_REFUSE',lambda x:x.update(day_controls=None),'DAY_CONTROLS_REQUIRED',day,day_context)
    altered('SESSION_DAY_INVENTEE_REFUSEE',lambda x:x['day_controls'].update(session_profile_id='UNKNOWN_TEST'),'DAY_SESSION_NOT_IN_HOST_CONTEXT',day,day_context)
    altered('DAY_PRIX_LIMITE_MANQUANT_REFUSE',lambda x:x['day_controls']['entry_order'].update(limit_price_text=None),'NATIVE_FIELDS_REJECTED',day,day_context)
    altered('DAY_FORCE_FLAT_MANQUANT_REFUSE',lambda x:x['day_controls'].update(overnight_policy='FORBID'),'NATIVE_FIELDS_REJECTED',day,day_context)
    altered('DAY_TTL_TYPE_INVALIDE_REFUSE',lambda x:x['day_controls'].update(signal_ttl=dict(value='60',unit='MINUTES',mode='WALL_CLOCK')),'OUTPUT_SCHEMA_INVALID',day,day_context)
    raw=json.dumps(p)
    rejected('JSON_CLE_DUPLIQUEE_REFUSEE',lambda:schema.validate_json('{"request_id":"'+p['request_id']+'",'+raw[1:]),'DUPLICATE_JSON_KEY')
    rejected('JSON_NON_FINI_REFUSE',lambda:schema.validate_json('{"x":NaN}'),'NONFINITE_JSON')
    rejected('SORTIE_TROP_LONGUE_REFUSEE',lambda:schema.validate_json(' '* (MAX_OUTPUT_BYTES+1)),'OUTPUT_TOO_LARGE')
    rejected('JSON_TRONQUE_REFUSE',lambda:schema.validate_json(raw[:-3]),'INVALID_JSON')
    import public_adam
    rejected('AUCUNE_AUTORISATION_PAR_FORMAT',public_adam.require_hypothesis_ready,'REAL_MODEL_OUTPUT_RETRIEVAL_AND_PROVIDER_BOUNDARIES_NOT_VALIDATED')
    # No native-store result or semantic truth field is promoted by this validation.
    record('SOURCE_SYNTHETIQUE_N_EST_PAS_PREUVE_SCIENTIFIQUE',good['semantic_relevance']=='NOT_VALIDATED' and
           good['live_retrieval_binding']=='NOT_ESTABLISHED_BY_THIS_COMPONENT')
    return cases,review


