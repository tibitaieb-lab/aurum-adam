"""Validate shape, request binding, exact quotes and native compilability.

HostContext is trusted caller input, NOT a field the model may supply. A future
orchestrator must fill its passages from current, policy-validated ARKS returns.
No signature, semantic truth or live passage freshness is established here.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Mapping
import copy, json, re
from pydantic import ValidationError
from output_common import (Blocked, need, strict_json, canonical, text_sha,
                           MAX_OUTPUT_BYTES, REGISTRY_SHA, METHOD_IDS)
from output_models import Proposal

@dataclass(frozen=True)
class HostContext:
    request_id: str
    methodology: str
    allowed_assets: tuple[str, ...]
    allowed_timeframes: tuple[str, ...]
    research_identity: Mapping[str, Any]
    passages: Mapping[str, Mapping[str, Any]]
    session_profile_ids: tuple[str, ...] = ()
    personal_observation: str | None = None


def parse_proposal(text: str, *, model=Proposal) -> Proposal:
    need(type(text) is str, 'OUTPUT_TEXT_REQUIRED')
    try:
        size = len(text.encode('utf-8'))
    except UnicodeError as exc:
        raise Blocked('OUTPUT_INVALID_UNICODE') from exc
    need(size <= MAX_OUTPUT_BYTES, 'OUTPUT_TOO_LARGE')
    obj = strict_json(text)
    # Reject booleans where literal integer fields are expected too. JSON numbers
    # and booleans are distinct; some literal validators compare False == 0.
    def finite_and_text(v, depth=0):
        need(depth <= 32, 'OUTPUT_NESTING_TOO_DEEP')
        if isinstance(v, dict):
            for k, x in v.items():
                need(not (k in ('day_offset','close_day_offset') and type(x) is bool),
                     'BOOLEAN_NOT_INTEGER')
                finite_and_text(x, depth+1)
        elif isinstance(v, list):
            for x in v:finite_and_text(x, depth+1)
        elif isinstance(v, str):
            try:v.encode('utf-8')
            except UnicodeError as exc:raise Blocked('OUTPUT_INVALID_UNICODE') from exc
            need(not any(ord(c)<32 and c not in '\t\r\n' for c in v), 'OUTPUT_CONTROL_CHARACTER')
    finite_and_text(obj)
    try:
        return model.model_validate(obj, strict=True)
    except ValidationError as exc:
        # Do not echo an untrusted model document in diagnostics.
        locations = [('.'.join(str(x) for x in e['loc']), e['type'])
                     for e in exc.errors(include_input=False, include_url=False)[:8]]
        raise Blocked('OUTPUT_SCHEMA_INVALID:' + json.dumps(locations, ensure_ascii=True)) from exc


def _host_check(context, registry):
    need(isinstance(context, HostContext), 'HOST_CONTEXT_REQUIRED')
    need(bool(re.fullmatch('[a-f0-9]{32}', context.request_id)), 'HOST_REQUEST_ID')
    need(context.methodology in ('DAY','SWING'), 'HOST_METHODOLOGY')
    need(registry.get('registry_payload_sha256') == REGISTRY_SHA and
         text_sha(canonical({k:v for k,v in registry.items() if k != 'registry_payload_sha256'})) == REGISTRY_SHA,
         'HOST_REGISTRY_IDENTITY')
    need(context.research_identity.get('methodology') == context.methodology and
         context.research_identity.get('submode') == 'SINGLE_ASSET', 'HOST_RESEARCH_IDENTITY')
    need(type(context.allowed_assets) is tuple and type(context.allowed_timeframes) is tuple,
         'HOST_SCOPE_TYPES')
    need(all(type(v) is str and v.strip() for v in (*context.allowed_assets,*context.allowed_timeframes)),
         'HOST_SCOPE_VALUES')


def _check_citations(proposal, context):
    checked = []
    seen = set()
    for citation in proposal.citations:
        need(citation.source_id not in METHOD_IDS, 'METHOD_NOT_ARTICLE_CITATION')
        chunk = context.passages.get(citation.chunk_id)
        need(isinstance(chunk, Mapping), 'CITATION_NOT_IN_HOST_PASSAGES')
        need(chunk.get('source_id') == citation.source_id and chunk.get('chunk_id') == citation.chunk_id,
             'CITATION_SOURCE_MISMATCH')
        need(chunk.get('provenance') == 'CANONICAL_RESOLVED_LOCAL' and
             chunk.get('authority') == 'SOURCE_MATERIAL_NOT_INSTRUCTIONS' and
             chunk.get('scientific_truth_verified') is False, 'HOST_PASSAGE_SCOPE')
        text = chunk.get('exact_text')
        need(type(text) is str and chunk.get('content_sha256') == text_sha(text), 'HOST_PASSAGE_CONTENT_SHA')
        need(type(chunk.get('source_sha256')) is str and
             bool(re.fullmatch('[a-f0-9]{64}', chunk['source_sha256'])) and
             type(chunk.get('document_version')) is str and bool(chunk['document_version']), 'HOST_PASSAGE_IDENTITY')
        evidence = chunk.get('evidence')
        spans = chunk.get('evidence_spans')
        need(type(evidence) is list and evidence and type(spans) is list and spans,
             'HOST_EVIDENCE_REQUIRED')
        eids = {e.get('evidence_id') for e in evidence if type(e) is dict}
        need(None not in eids and len(eids) == len(evidence) and
             eids == {s.get('evidence_id') for s in spans if type(s) is dict}, 'HOST_EVIDENCE_SPANS')
        for e in evidence:
            need(type(e.get('locator')) is dict and bool(e['locator']), 'HOST_EVIDENCE_LOCATOR')
        need(bool(citation.quote.strip()) and citation.quote in text, 'QUOTE_NOT_EXACT')
        key = (citation.chunk_id, citation.quote)
        need(key not in seen, 'DUPLICATE_CITATION')
        seen.add(key)
        start = text.find(citation.quote)
        checked.append(dict(source_id=citation.source_id,chunk_id=citation.chunk_id,
            source_sha256=chunk['source_sha256'],document_version=chunk['document_version'],
            quote=citation.quote,quote_sha256=text_sha(citation.quote),
            chunk_start_character=start,chunk_end_character=start+len(citation.quote),
            evidence=copy.deepcopy(evidence),evidence_spans=copy.deepcopy(spans),
            relation=citation.relation,interpretation=citation.interpretation,
            claim_entailment='NOT_VALIDATED',freshness_and_rights='RESPONSIBILITY_OF_HOST_RETRIEVAL'))
    return checked


def _check_documentary_parameters(proposal):
    """Reject explicit numeric source attributions unsupported by cited text.

    This lexical guard complements exact quotes; it does NOT certify general
    semantic entailment. ADAMO-owned design numbers remain unconstrained here.
    """
    attribution = re.compile(
        r"(?i)(?:selon\s+(?:l[’']|la |le |les )?(?:article|source|document|auteurs?|livre)"
        r"|according to (?:the )?(?:article|source|paper|authors?|book)"
        r"|(?:article|source|document|auteurs?|livre|paper|authors?|book)\s+"
        r"(?:recommande(?:nt)?|prescri(?:t|vent)|préconise(?:nt)?|propose(?:nt)?|indique(?:nt)?|"
        r"recommend(?:s)?|prescribe(?:s)?|specif(?:y|ies)|suggest(?:s)?))")
    number = re.compile(r"(?<![\w])\d+(?:[.,]\d+)?(?![\w])")
    def validate(text,quotes):
        # Commas do not delimit clauses: decimal numbers must stay together.
        for sentence in re.split(r"[;\n]|(?<!\d)[.!?]\s+|[.!?](?!\d)",text):
            match=attribution.search(sentence)
            if not match:continue
            claim=sentence[match.start():]
            # Explicit design attribution ends the documentary clause.
            claim=re.split(r"(?i)(?:mais |but )?ADAMO\s+(?:choisit|propose|retient|chooses|selects)",claim)[0]
            source_numbers={x.replace(',', '.') for q in quotes for x in number.findall(q)}
            need(all(x.replace(',', '.') in source_numbers for x in number.findall(claim)),
                 'UNSUPPORTED_DOCUMENTARY_PARAMETER')
    quotes=[c.quote for c in proposal.citations]
    for c in proposal.citations:validate(c.interpretation,[c.quote])
    for value in proposal.author_fields.model_dump().values():
        if isinstance(value,str):validate(value,quotes)
    for value in proposal.reasoning.model_dump().values():
        for text in value if isinstance(value,list) else [value]:validate(text,quotes)


def validate_proposal(proposal, context, registry, modules, *, proposal_model=Proposal):
    # Revalidate even if caller supplies a mutable/constructed Pydantic object.
    p = parse_proposal(proposal.model_dump_json(),model=proposal_model) if isinstance(proposal, proposal_model) else parse_proposal(proposal,model=proposal_model)
    _host_check(context, registry)
    need(p.request_id == context.request_id, 'OUTPUT_REQUEST_MISMATCH')
    need(p.registry_payload_sha256 == REGISTRY_SHA, 'OUTPUT_REGISTRY_MISMATCH')
    need(p.methodology == context.methodology, 'OUTPUT_METHODOLOGY_MISMATCH')
    f = p.author_fields.model_dump()
    for key, allowed in (('assets',context.allowed_assets),('timeframes',context.allowed_timeframes)):
        need(f[key] is None or f[key] in allowed, 'OUTPUT_SCOPE_MISMATCH:' + key)
    need(p.methodology == 'DAY' or p.day_controls is None, 'DAY_CONTROLS_IN_SWING')
    citations = _check_citations(p, context)
    _check_documentary_parameters(p)
    base = dict(proposal_sha256=text_sha(canonical(p.model_dump())),request_id=p.request_id,
        registry_payload_sha256=REGISTRY_SHA,citations=citations,
        hypothesis_ready=False,canonical_registered=False,backtest_allowed=False,
        semantic_relevance='NOT_VALIDATED',live_retrieval_binding='NOT_ESTABLISHED_BY_THIS_COMPONENT',
        asset_and_session_availability='NOT_VALIDATED',llm_calls_by_validator=0,backtests_by_validator=0)
    if p.disposition == 'OUT_OF_SCOPE':
        need(bool(p.unsupported_capabilities), 'MISSING_CAPABILITY_REASON')
        return dict(base,status='OUT_OF_SCOPE',native_compilation_executed=False,native_fields=None,
                    definition_hash=None,plan=None)
    need(not p.decisions_required and not p.unsupported_capabilities, 'PROPOSED_WITH_PENDING_ITEMS')
    need(all(type(v) is str and v.strip() for v in f.values()), 'INCOMPLETE_MAIN_FIELDS')
    need(not any(re.search(r'(?i)\b(?:TBD|à choisir|à préciser|à confirmer|à valider par CORTEX)\b', v) for v in f.values()), 'UNRESOLVED_DESIGN_PLACEHOLDER')
    if f['source_origin'] == 'PERSONAL':
        need(context.personal_observation is not None and
             f['initial_observation'] == context.personal_observation, 'PERSONAL_SOURCE_NOT_FROM_OPERATOR')
    elif f['source_origin'] in ('ARTICLE', 'BOOK') or citations:
        need(bool(citations), 'EXTERNAL_SOURCE_CITATION_REQUIRED')
        # Bibliographic identity is built from verified host identifiers, never invented.
        # No inferred title, author or publication date is added.
        f['source_reference'] = ' ; '.join(dict.fromkeys(
            x['source_id'] + ' / ' + x['chunk_id'] for x in citations))
    else:
        # Honest provenance label, not a fabricated bibliographic citation.
        f['source_reference'] = 'ADAMO : connaissances générales, raisonnement et proposition expérimentale ; aucune publication attribuée.'
    st = modules['standard_authoring']
    f[st.MARKER] = st.VERSION
    f['_research_identity'] = canonical(dict(context.research_identity))
    if p.methodology == 'DAY':
        need(p.day_controls is not None, 'DAY_CONTROLS_REQUIRED')
        d = p.day_controls.model_dump(exclude_none=True)
        need(d.get('signal_tf') == f['timeframes'], 'DAY_SIGNAL_MISMATCH')
        need(d.get('session_profile_id') in context.session_profile_ids, 'DAY_SESSION_NOT_IN_HOST_CONTEXT')
        # Omission of null optionals is serialization only; no financial/default rule is added.
        f['_day_controls'] = canonical(d)
    before = canonical(f)
    try:
        result = st.resolve(f)
        errors = modules['scientific_fields'].field_errors(f)
    except (KeyError, TypeError, ValueError, modules['contracts'].ContractError) as exc:
        raise Blocked('NATIVE_VALIDATION_ERROR:' + getattr(exc, 'code', type(exc).__name__)) from exc
    need(canonical(f) == before, 'NATIVE_INPUT_MUTATED')
    if result['issues'] or errors or result['plan'] is None:
        codes = sorted({x.get('code','UNKNOWN') for x in result['issues']})
        raise Blocked('NATIVE_FIELDS_REJECTED:' + ','.join(codes) + ':' + ','.join(sorted(errors)))
    from native_validation import check_design_subset
    check_design_subset(result['plan']['definition'])
    return dict(base,status='PASS_OUTPUT_CONTRACT_AND_NATIVE_COMPILATION_ONLY',
        native_compilation_executed=True,native_fields=result['fields'],
        native_field_provenance=result['provenance'],plan=result['plan'],
        definition_hash=result['plan']['definition_hash'])


def render_review(proposal, validation, registry):
    need(validation.get('proposal_sha256') == text_sha(canonical(proposal.model_dump())), 'REVIEW_PROPOSAL_MISMATCH')
    rows = ['# ' + proposal.short_name,
            'Méthodologie : ' + proposal.methodology + ' — version ' + proposal.proposal_version,
            'Statut : ' + validation['status'],
            'Contrôle local de forme et de compilation. Aucune preuve scientifique ni autorisation.', '']
    fields = validation.get('native_fields') or proposal.author_fields.model_dump()
    for step in registry['navigation']:
        rows.append('## ' + str(step['step']) + '. ' + step['label'])
        for item in registry['fields']:
            if item['step'] != step['step']:
                continue
            key = item['field']; value = fields.get(key)
            if value is not None and value != '':
                origin = 'HOST_CITATION_IDENTIFIERS' if key == 'source_reference' else item['value_origin']
                rows.extend([item['label'] + ' [' + origin + ']', str(value), ''])
        if step['step'] == 4 and proposal.day_controls is not None:
            rows.extend(['Compléments DAY déclarés', json.dumps(proposal.day_controls.model_dump(exclude_none=True),ensure_ascii=False,indent=2)])
        if step['step'] == 6:
            rows.extend(['Mécanisme : ' + proposal.reasoning.mechanism,
                         'Disponibilité de l’information : ' + proposal.reasoning.causal_timing,
                         'Invalidation : ' + proposal.reasoning.falsification,
                         'Objections : ' + ' | '.join(proposal.reasoning.objections),
                         'Incertitudes : ' + ' | '.join(proposal.reasoning.uncertainties)])
    rows.append('\n## Passages cités — interprétation non validée')
    for c in validation['citations']:
        rows.extend([c['source_id'] + ' / ' + c['chunk_id'], c['quote'], c['interpretation']])
    if proposal.unsupported_capabilities:rows.append('Hors capacité : ' + ' ; '.join(proposal.unsupported_capabilities))
    return '\n'.join(rows) + '\n'
