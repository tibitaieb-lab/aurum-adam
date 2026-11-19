"""Offline public ADAM path built from the existing proposal validators."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'output_contract_v1'))

from output_common import Blocked, canonical, dependency_state, read_json, verify_self
from output_models import Proposal
from proposal_validation import HostContext, parse_proposal, validate_proposal, render_review
from native_validation import native_compiler
from citation_materializer_v2.materializer import materialize_research_citations


class LocalProposalSchema:
    """Local Pydantic validation; no model SDK is used or simulated."""
    def validate_json(self, text):
        return parse_proposal(text)

    def json_schema(self):
        return Proposal.model_json_schema()


def require_hypothesis_ready():
    raise Blocked('REAL_MODEL_OUTPUT_RETRIEVAL_AND_PROVIDER_BOUNDARIES_NOT_VALIDATED')


def load_context(path):
    value = read_json(path)
    if type(value) is not dict:
        raise Blocked('HOST_CONTEXT_OBJECT_REQUIRED')
    # These are serialization conversions of operator-owned scope arrays,
    # never permission inferred from a generated proposal.
    for key in ('allowed_assets', 'allowed_timeframes', 'session_profile_ids'):
        items = value.get(key, [])
        if type(items) is not list or not all(type(x) is str for x in items):
            raise Blocked('HOST_SCOPE_TYPES')
        value[key] = tuple(items)
    try:
        return HostContext(**value)
    except TypeError as error:
        raise Blocked('HOST_CONTEXT_SCHEMA') from error


def validate(proposal, context):
    """Exact citation materialization, unchanged validators, bundled compiler."""
    verify_self()
    _, registry = dependency_state()
    parsed = parse_proposal(canonical(proposal))
    audit = []
    if parsed.citations:
        research = [dict(source_id=x['source_id'], chunk_id=x['chunk_id'], excerpt=x['exact_text'])
                    for x in context.passages.values()]
        proposal, audit = materialize_research_citations(parsed.model_dump(), research)
        parsed = parse_proposal(canonical(proposal))
    with native_compiler(registry) as modules:
        result = validate_proposal(parsed, context, registry, modules)
    result.update(execution_mode='PUBLIC_OFFLINE_VALIDATION', model_calls=0,
                  arks_live_queries=0, external_network_calls=0,
                  citation_materialization=audit)
    return parsed, result, render_review(parsed, result, registry)
