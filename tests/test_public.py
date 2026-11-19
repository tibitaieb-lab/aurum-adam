import copy
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

import public_adam as public
from output_common import Blocked, canonical, dependency_state, load_registry
from native_validation import native_compiler
from proposal_validation import parse_proposal, validate_proposal, _host_check
from source_contract_cases import fixture, run_cases
from citation_materializer_v2 import materializer as citations

ROOT = public.ROOT
sys.path.insert(0, str(ROOT / 'tools'))
import demo


class SourceContractsTests(unittest.TestCase):
    def test_48_source_regressions_swing_day_and_rejections(self):
        _, registry = dependency_state()
        with native_compiler(registry) as modules:
            cases, review = run_cases(public.LocalProposalSchema(), registry, modules)
        self.assertEqual(len(cases), 48)
        self.assertIn('REVUE_SIX_ETAPES_ORDRE_UI', cases)
        self.assertIn('TEST DE FORMAT', review)


class PublicPathTests(unittest.TestCase):
    def sample(self):
        return public.read_json(ROOT / 'examples/proposal.json'), public.load_context(ROOT / 'examples/host-context.json')

    def test_shipped_example_compiles_without_approval_or_provider(self):
        proposal, context = self.sample()
        original = copy.deepcopy(proposal)
        parsed, result, review = public.validate(proposal, context)
        self.assertEqual(proposal, original)
        self.assertTrue(result['native_compilation_executed'])
        self.assertFalse(result['hypothesis_ready'])
        self.assertFalse(result['backtest_allowed'])
        self.assertFalse(result['canonical_registered'])
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(result['arks_live_queries'], 0)
        self.assertEqual(result['semantic_relevance'], 'NOT_VALIDATED')
        self.assertIn(parsed.citations[0].quote, review)

    def test_repeatable_definition_hash(self):
        proposal, context = self.sample()
        first = public.validate(proposal, context)[1]
        second = public.validate(proposal, context)[1]
        self.assertEqual(first['definition_hash'], second['definition_hash'])
        self.assertEqual(first['native_fields'], second['native_fields'])

    def test_cli_writes_review_in_requested_directory(self):
        before = list(sys.argv)
        try:
            with tempfile.TemporaryDirectory() as folder:
                sys.argv = ['demo.py', '--output', folder]
                self.assertEqual(demo.main(), 0)
                files = {p.name for p in Path(folder).iterdir()}
                self.assertEqual(files, {'proposal-validated.json','validation.json','review.txt','review.html'})
                result = json.loads((Path(folder) / 'validation.json').read_bytes())
                self.assertFalse(result['backtest_allowed'])
        finally:
            sys.argv = before

    def test_html_escapes_untrusted_text(self):
        proposal, context = self.sample()
        proposal['author_fields']['title'] = '<script>alert(1)</script>'
        parsed, result, review = public.validate(proposal, context)
        page = demo.review_html(parsed, result, review)
        self.assertNotIn('<script>', page)
        self.assertIn('&lt;script&gt;', page)

    def test_context_cannot_be_supplied_as_proposal_fields(self):
        proposal, context = self.sample()
        proposal['host_context'] = {'passages': {}}
        with self.assertRaisesRegex(Blocked, 'OUTPUT_SCHEMA_INVALID'):
            public.validate(proposal, context)

    def test_unknown_context_fields_rejected(self):
        context = public.read_json(ROOT / 'examples/host-context.json')
        context['api_key'] = 'EXPLICIT_DUMMY_NOT_A_CREDENTIAL'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'context.json'
            path.write_text(json.dumps(context), encoding='utf-8')
            with self.assertRaisesRegex(Blocked, 'HOST_CONTEXT_SCHEMA'):
                public.load_context(path)

    def test_fictional_source_equals_host_passage(self):
        _, context = self.sample()
        source = (ROOT / 'examples/source-fictive.txt').read_text(encoding='utf-8').rstrip('\n')
        self.assertEqual(next(iter(context.passages.values()))['exact_text'], source)

    def test_altered_native_registry_refused(self):
        registry = load_registry()
        registry['scope'] = 'CHANGED'
        with self.assertRaisesRegex(Blocked, 'PUBLIC_REGISTRY_MISMATCH'):
            with native_compiler(registry):
                pass

    def test_portfolio_unavailable_is_explicit(self):
        from day_v2.kernel.compiler import compile_definition
        from day_v2.kernel.contracts import ContractError
        with self.assertRaisesRegex(ContractError, 'portefeuille'):
            compile_definition({'version':'AURUM_PORTFOLIO_DEFINITION_V1'})


class CitationTests(unittest.TestCase):
    SOURCE = 'Au labo fictif, un signal pré-\ndit une forme eﬃciente — « possible » uniquement.'

    def span(self, text):
        start, end, kinds = citations.find_layout_span(text, self.SOURCE)
        return self.SOURCE[start:end], kinds

    def test_exact_quote(self):
        text, kinds = self.span('Au labo fictif')
        self.assertEqual(text, 'Au labo fictif')
        self.assertEqual(kinds, [])

    def test_layout_is_materialized_to_source_bytes(self):
        text, kinds = self.span('signal prédit')
        self.assertEqual(text, 'signal pré-\ndit')
        self.assertIn('LINE_END_HYPHENATION', kinds)

    def test_ligature(self):
        text, kinds = self.span('forme efficiente')
        self.assertIn('ﬃ', text)
        self.assertIn('LIGATURE', kinds)

    def test_changed_word_refused(self):
        with self.assertRaises(citations.CitationMaterializationError):
            self.span('signal garantit')

    def test_changed_case_refused(self):
        with self.assertRaises(citations.CitationMaterializationError):
            self.span('Signal prédit')

    def test_wrong_source_and_chunk_refused(self):
        with self.assertRaisesRegex(citations.CitationMaterializationError, 'PAIR_NOT_IN_RESEARCH_CONTEXT'):
            citations.materialize_research_citations({'citations': [{'source_id':'X','chunk_id':'C','quote':'Au labo fictif'}]},
                [{'source_id':'S','chunk_id':'C','excerpt':self.SOURCE}])

    def test_duplicate_after_materialization_refused(self):
        raw = {'citations': [{'source_id':'S','chunk_id':'C','quote':'signal prédit'},
                             {'source_id':'S','chunk_id':'C','quote':'signal pré-\ndit'}]}
        with self.assertRaisesRegex(citations.CitationMaterializationError, 'DUPLICATE_CITATION'):
            citations.materialize_research_citations(raw, [{'source_id':'S','chunk_id':'C','excerpt':self.SOURCE}])

    def test_invented_text_classified_without_echo(self):
        invented = 'Une promesse fictive qui ne figure dans aucun passage.'
        result = citations.classify_quote_gap(invented, self.SOURCE)
        self.assertEqual(result['gap_type'], 'd')
        self.assertNotIn(invented, json.dumps(result))


class OfflineGuardTests(unittest.TestCase):
    def test_dns_refused_before_resolution(self):
        with self.assertRaisesRegex(RuntimeError, 'OFFLINE_TRANSPORT_FORBIDDEN'):
            socket.getaddrinfo('example.invalid', 443)

    def test_subprocess_refused_before_launch(self):
        with self.assertRaisesRegex(RuntimeError, 'OFFLINE_TRANSPORT_FORBIDDEN'):
            subprocess.run([sys.executable, '-c', 'print(1)'], check=True)

    def test_no_model_sdk_imported(self):
        self.assertNotIn('openai', sys.modules)
        self.assertNotIn('agents', sys.modules)

    def test_no_hypothesis_approval(self):
        with self.assertRaisesRegex(Blocked, 'NOT_VALIDATED'):
            public.require_hypothesis_ready()
