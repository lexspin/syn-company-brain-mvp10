"""Exercise proposal discovery without live records, models or mutation."""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
from learning_review import review
from lifecycle import recall


def record(kind, id, version=1, archived=False, **data):
    return {'kind': kind, 'id': id, 'version': version, 'archived': archived, 'data': {'name': id, **data}}


class LearningReviewTests(unittest.TestCase):
    def setUp(self):
        self.body = 'Reconcile original receipt before uncertain retry.'
        self.proposal = record('memory', 'learning-one', status='candidate', type='skill-improvement', origin='inferred',
            proposed_instructions=self.body, candidate_sha256=hashlib.sha256(self.body.encode()).hexdigest(),
            source_bindings={'memory:source': 1}, outcome_request_id='outcome', outcome_receipt='a'*32,
            target={'kind': 'skill-update', 'id': 'recovery', 'version': 1, 'surface': 'registry-only'},
            scope='Receipt recovery', rationale='Avoid duplicate effects',
            acceptance={'normal': 'Existing receipt returns output', 'counterexample': 'Uncertain effects never replay'})
        self.project = record('project', 'one', refs=['memory:source', 'skill:recovery'], path='C:/test', scope='Scoped work')
        self.source = record('memory', 'source', status='accepted', content='Receipt recovery succeeded.', source='Checked result')
        self.target = record('skill', 'recovery', instructions='Baseline')
        self.state = {'objects': [self.project, self.source, self.target, self.proposal],
                      'memory_freshness': {'source': {'current': True}, 'learning-one': {'current': False}},
                      '_view': {'asof': datetime.now(timezone.utc).isoformat(), 'stale': False}, 'worker_busy': False}

    def test_normal_candidate_is_a_review_hint_without_input_mutation(self):
        before = copy.deepcopy(self.state)
        result = review(self.state, 'receipt', 'one')
        card = result['candidates'][0]
        self.assertEqual(card['id'], 'learning-one')
        self.assertEqual(card['status'], 'unreviewed-proposal')
        self.assertEqual(card['drift'], [])
        self.assertEqual(card['scope_links'], ['memory:source'])
        self.assertEqual(card['acceptance_descriptions']['normal'], 'Existing receipt returns output')
        self.assertIn('not executed tests', result['next'])
        self.assertEqual(self.state, before)

    def test_scope_uses_direct_candidate_source_or_outcome_links_only(self):
        unrelated = copy.deepcopy(self.proposal)
        unrelated['id'] = 'learning-unrelated'
        unrelated['data']['source_bindings'] = {'memory:other': 1}
        unrelated['data']['outcome_request_id'] = 'other-outcome'
        self.state['objects'].extend([unrelated, record('memory', 'other'), record('memory', 'other-outcome')])
        # A common target skill and same matching text cannot admit unrelated work.
        self.assertEqual([r['id'] for r in review(self.state, 'receipt', 'one')['candidates']], ['learning-one'])
        self.project['data']['refs'] = []
        self.source['data']['refs'] = ['project:one']
        self.assertEqual(len(review(self.state, project_id='one')['candidates']), 1)
        self.source['data']['refs'] = []
        self.state['objects'].append(record('memory', 'outcome', refs=['project:one']))
        self.assertEqual(len(review(self.state, project_id='one')['candidates']), 1)
        self.state['objects'][-1]['data']['refs'] = []
        self.proposal['data']['refs'] = ['project:one']
        self.assertEqual(len(review(self.state, project_id='one')['candidates']), 1)

    def test_source_and_target_drift_and_missing_hash_are_explicit(self):
        for field, value, expected in [('version', 2, 'Source version changed.'), ('archived', True, 'Source archived.')]:
            original = self.source[field]; self.source[field] = value
            self.assertIn(expected, review(self.state)['candidates'][0]['sources'][0]['drift'])
            self.source[field] = original
        self.state['memory_freshness']['source']['current'] = False
        self.assertIn('not current', review(self.state)['candidates'][0]['sources'][0]['drift'])
        self.state['objects'].remove(self.source)
        self.assertEqual(review(self.state)['candidates'][0]['sources'][0]['drift'], 'Source missing.')
        self.target['version'] = 2
        self.assertIn('Target skill version changed.', review(self.state)['candidates'][0]['drift'])
        self.proposal['data']['candidate_sha256'] = '0'*64
        self.assertIn('Candidate instruction hash missing or changed.', review(self.state)['candidates'][0]['drift'])

    def test_new_target_candidates_are_review_only_and_conflicts_visible(self):
        for kind, object_kind in [('new-skill', 'skill'), ('new-workflow', 'loop')]:
            with self.subTest(kind=kind):
                self.proposal['data']['type'] = 'learning-candidate'
                self.proposal['data']['target'] = {'kind': kind, 'id': 'new-target', 'version': 0, 'surface': 'registry-only'}
                card = review(self.state)['candidates'][0]
                self.assertFalse(card['creation_available']); self.assertEqual(card['drift'], [])
                conflict = record(object_kind, 'new-target')
                self.state['objects'].append(conflict)
                self.assertIn('New target baseline changed or target already exists.', review(self.state)['candidates'][0]['drift'])
                self.state['objects'].remove(conflict)

    def test_absent_archived_accepted_and_nonprocedure_records_do_not_appear(self):
        self.assertEqual(review({'objects': [], '_view': {}})['candidates'], [])
        for field, value in [('status', 'accepted'), ('type', 'research')]:
            old = self.proposal['data'][field]; self.proposal['data'][field] = value
            self.assertEqual(review(self.state)['candidates'], [])
            self.proposal['data'][field] = old
        self.proposal['archived'] = True
        self.assertEqual(review(self.state)['candidates'], [])

    def test_bounded_output_exact_ranking_and_stale_publication(self):
        for i in range(40):
            row = copy.deepcopy(self.proposal); row['id'] = f'learning-copy-{i:02d}'
            self.state['objects'].append(row)
        result = review(self.state, 'memory:learning-one receipt', limit=2)
        self.assertEqual(result['candidates'][0]['id'], 'learning-one')
        self.assertEqual(len(result['candidates']), 2); self.assertTrue(result['truncated'])
        self.state['_view']['stale'] = True
        self.assertTrue(review(self.state)['publication']['stale'])
        self.proposal['data']['scope'] = 'x'*4000
        self.proposal['data']['proposed_instructions'] = 'x'*5000
        card = next(r for r in review(self.state, 'learning-one')['candidates'] if r['id'] == 'learning-one')
        self.assertEqual(len(card['scope']), 1200); self.assertEqual(len(card['instruction_excerpt']), 1200)
        self.assertTrue(card['instructions_truncated'])
        self.proposal['data']['source_bindings'] = {f'memory:missing-{i}': 1 for i in range(40)}
        card = review(self.state, 'learning-one')['candidates'][0]
        self.assertEqual(len(card['sources']), 32); self.assertTrue(card['sources_truncated'])

    def test_source_versions_fallback_and_invalid_arguments(self):
        del self.proposal['data']['source_bindings']
        self.proposal['data']['source_versions'] = {'source': 1}
        self.assertEqual(review(self.state, project_id='one')['candidates'][0]['sources'][0]['ref'], 'memory:source')
        for kwargs in [{'limit': 0}, {'limit': 33}, {'limit': True}, {'query': 'x'*12001}, {'project_id': '../one'}, {'project_id': 'missing'}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): review(self.state, **kwargs)

    def test_malformed_proposal_metadata_is_bounded_and_cannot_certify_readiness(self):
        self.proposal['data'].update(candidate_sha256={'untrusted': 'x'*20000}, outcome_receipt='x'*20000,
            source_bindings={'memory:'+'x'*20000: {'version': 'x'*20000}},
            target={'kind': 'skill-update', 'id': 'x'*20000, 'version': {}, 'surface': 'x'*20000})
        card = review(self.state)['candidates'][0]
        self.assertIsNone(card['candidate_sha256']); self.assertIsNone(card['sources'][0]['version'])
        self.assertLessEqual(len(card['sources'][0]['ref']), 160)
        self.assertLessEqual(len(card['outcome_receipt']), 160)
        self.assertIn('Invalid target binding.', card['drift'])
        self.assertLess(len(json.dumps(card)), 8000)

    def test_cli_is_read_only_and_candidates_stay_out_of_ordinary_recall(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'runtime') as folder:
            root = Path(folder); (root/'data').mkdir()
            (root/'data/state.json').write_text(json.dumps(self.state), encoding='utf-8')
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            command = [sys.executable, '-X', 'utf8', str(Path(__file__).resolve().parents[1]/'app/lifecycle.py'), '--root', str(root),
                       'learning-review', '--project', 'one', '--query', 'receipt', '--limit', '2']
            process = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout)['candidates'][0]['id'], 'learning-one')
            with patch('lifecycle.history_search', return_value=[]), patch('lifecycle.verify_history'):
                recalled = recall(root, 'receipt', 'one')
            self.assertEqual([r['id'] for r in recalled['memory']], ['source'])
            after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(before, after)
            self.assertFalse((root/'store').exists()); self.assertFalse((root/'runtime').exists())


if __name__ == '__main__': unittest.main()
