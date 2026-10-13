"""Curation must preserve skills and separate telemetry observations."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
from skill_curation import curate
from brain import Brain


def row(kind, id, **data):
    return {'kind': kind, 'id': id, 'version': 1, 'archived': False, 'data': {'name': id, **data}}


class SkillCurationTests(unittest.TestCase):
    def setUp(self):
        self.first = row('skill', 'first', instructions='Keep exact source identity.')
        self.second = row('skill', 'second', instructions='Keep a separate role.')
        self.project = row('project', 'one', refs=['skill:first'])
        self.state = {'objects': [self.first, self.second, self.project], 'memory_freshness': {},
                      '_view': {'asof': datetime.now(timezone.utc).isoformat(), 'stale': False}}

    def test_new_never_used_and_ambiguous_methods_remain(self):
        before = copy.deepcopy(self.state)
        result = curate(self.state)
        self.assertEqual(result['recommendation_counts']['retain'], 2)
        self.assertTrue(all(r['recommendation'] == 'retain' for r in result['recommendations']))
        self.assertTrue(all(r['usage']['reported_execution_events'] == 0 for r in result['recommendations']))
        self.assertEqual(before, self.state)
        self.assertIn('unreported use remains unknown', result['telemetry']['coverage'])

    def test_same_names_are_not_duplicates_exact_body_only_requests_review(self):
        self.first['data']['name'] = self.second['data']['name'] = 'Shared name'
        self.assertEqual(curate(self.state)['recommendation_counts']['review-overlap'], 0)
        self.second['data']['instructions'] = self.first['data']['instructions']
        before = copy.deepcopy(self.state); result = curate(self.state)
        self.assertEqual(result['recommendation_counts']['review-overlap'], 2)
        self.assertEqual(result['recommendations'][0]['identical_body_peers'], [{'ref': 'skill:second', 'version': 1}])
        self.assertIn('separately authorized', result['recommendations'][0]['review_gate'][-1])
        self.assertEqual(before, self.state)
        self.second['data']['instructions'] += '\n'
        self.assertEqual(curate(self.state)['recommendation_counts']['review-overlap'], 0)

    def test_scheduled_loop_and_owner_metadata_and_running_work_protected(self):
        self.state['objects'].append(row('loop', 'scheduled', execution={'skill_id': 'first'}, schedule={'interval': 'daily'}))
        self.first['data'].update(pinned=True, canonical=True, owner_direction='Retain this method.')
        task = {'task_id': 'running-task', 'status': 'running', 'area_refs': ['skill:first']}
        card = curate(self.state, [task])['recommendations'][0]
        self.assertEqual(card['workflow_consumers'], [{'ref': 'loop:scheduled', 'version': 1}])
        self.assertEqual(card['active_tasks'], ['running-task'])
        self.assertEqual(len(card['protection']), 5)
        self.assertEqual(card['recommendation'], 'retain')
        task['status'] = 'stale'
        self.assertEqual(curate(self.state, [task])['recommendations'][0]['active_tasks'], [])

    def test_skill_referenced_only_in_documented_local_step_is_protected(self):
        # brain.validate and snapshot use raw skill ID in steps[].skill,
        # separately from graph refs and native execution.skill_id.
        loop = row('loop', 'step-loop', refs=[],
            steps=[{'agent': 'reviewer', 'skill': 'first', 'tool': 'validate', 'instruction': 'Check sources.'}])
        self.state['objects'].append(loop)
        registry = {('skill', 'first'): self.first,
                    ('agent', 'reviewer'): row('agent', 'reviewer', tools=['validate'], skills=['first'])}
        # Exercise the real validator without constructing a Brain or writer.
        Brain.validate(SimpleNamespace(get=lambda kind, id: registry[(kind, id)]), 'loop', 'step-loop', loop['data'])
        card = curate(self.state)['recommendations'][0]
        self.assertEqual(card['workflow_consumers'], [{'ref': 'loop:step-loop', 'version': 1}])
        self.assertTrue(card['protection'])
        self.assertEqual(card['recommendation'], 'retain')
        loop['data']['refs'] = ['skill:first']
        loop['data']['steps'].append(copy.deepcopy(loop['data']['steps'][0]))
        self.assertEqual(len(curate(self.state)['recommendations'][0]['workflow_consumers']), 1)
        self.state['objects'][-1]['archived'] = True
        self.assertEqual(curate(self.state)['recommendations'][0]['workflow_consumers'], [])

    def test_reads_planned_and_catalog_relationships_are_not_execution(self):
        edge = {'source': 'skill:first', 'target': 'project:one', 'relation': 'executes'}
        task = {'task_id': 'task', 'status': 'completed', 'edges': [edge]}
        history = {'task': {'events': [
            {'event_id': 'read', 'reads': [{'reference': 'skill:first'}]},
            {'event_id': 'catalog', 'edges': [edge]},
            {'event_id': 'planned', 'edges': [edge | {'observation': 'planned'}]},
            {'event_id': 'related', 'edges': [edge | {'observation': 'observed', 'relation': 'uses'}]},
            {'event_id': 'executed', 'edges': [edge | {'observation': 'observed'}]}]}}
        usage = curate(self.state, [task], history)['recommendations'][0]['usage']
        self.assertEqual(usage['source_read_events'], 1)
        self.assertEqual(usage['observed_relationship_events'], 2)
        self.assertEqual(usage['reported_execution_events'], 1)
        self.assertEqual(curate(self.state, [task])['recommendations'][0]['usage']['reported_execution_events'], 0)

    def test_project_scope_drift_and_bounded_totals(self):
        self.assertEqual(curate(self.state, project_id='one')['scoped_skills_total'], 1)
        self.project['data']['refs'] = []
        self.first['data']['refs'] = ['project:one']
        self.first['data']['source_versions'] = {'source': 1}
        self.state['objects'].append(row('memory', 'source'))
        card = curate(self.state, project_id='one')['recommendations'][0]
        self.assertEqual(card['recommendation'], 'review-source-drift')
        self.assertIn('not current accepted', card['source_drift'][0])
        self.state['memory_freshness']['source'] = {'current': True}
        self.state['objects'][-1]['version'] = 2
        self.assertIn('version changed', curate(self.state, project_id='one')['recommendations'][0]['source_drift'][0])
        self.state['_view']['stale'] = True
        for i in range(40): self.state['objects'].append(row('skill', 'copy-'+str(i), instructions=self.first['data']['instructions']))
        result = curate(self.state, limit=2)
        self.assertEqual(result['skills_total'], 42); self.assertEqual(len(result['recommendations']), 2)
        self.assertTrue(result['truncated']); self.assertTrue(result['publication']['stale'])
        self.assertTrue(result['recommendations'][0]['peers_truncated'])

    def test_telemetry_coverage_and_invalid_arguments(self):
        result = curate(self.state, [{'task_id': 'task'}], {'task': {'events': [], 'truncated': True}})
        self.assertTrue(result['telemetry']['truncated_or_at_bound'])
        for kwargs in [{'limit': 0}, {'limit': 33}, {'limit': True}, {'project_id': 'missing'}, {'project_id': '../one'}, {'query': 'x'*1001}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): curate(self.state, **kwargs)

    def test_query_applies_before_cap_without_changing_curation_or_scope(self):
        for i in range(40): self.state['objects'].append(row('skill', 'copy-'+str(i), instructions='Unrelated procedure.'))
        result = curate(self.state, query='skill:second', limit=1)
        self.assertEqual(result['skills_total'], 42); self.assertEqual(result['query_matches_total'], 1)
        self.assertEqual(result['recommendations'][0]['ref'], 'skill:second')
        self.assertEqual(curate(self.state, project_id='one', query='skill:second')['recommendations'], [])

    def test_linked_source_versions_are_visible_without_invented_binding(self):
        self.first['data']['refs'] = ['memory:source']
        self.state['objects'].append(row('memory', 'source'))
        self.state['memory_freshness']['source'] = {'current': True}
        source = curate(self.state)['recommendations'][0]['sources'][0]
        self.assertEqual(source['current_version'], 1)
        self.assertIsNone(source['version']); self.assertFalse(source['version_bound'])
        self.state['objects'][-1]['archived'] = True
        card = curate(self.state)['recommendations'][0]
        self.assertEqual(card['recommendation'], 'review-source-context'); self.assertEqual(card['source_drift'], [])
        self.assertEqual(card['sources'][0]['linked_source_status'], 'archived')
        self.state['objects'][-1]['archived'] = False
        self.first['data']['source_bindings'] = {'memory:source': 2}
        source = curate(self.state)['recommendations'][0]['sources'][0]
        self.assertTrue(source['version_bound']); self.assertEqual(source['drift'], 'version changed')

    def test_cli_reads_absent_activity_store_without_creating_files(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'runtime') as folder:
            root = Path(folder); (root/'data').mkdir()
            (root/'data/state.json').write_text(json.dumps(self.state), encoding='utf-8')
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            command = [sys.executable, '-X', 'utf8', str(Path(__file__).resolve().parents[1]/'app/lifecycle.py'), '--root', str(root),
                       'skill-curation', '--project', 'one', '--limit', '1']
            process = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout)['scoped_skills_total'], 1)
            self.assertEqual(before, {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()})
            self.assertFalse((root/'runtime').exists()); self.assertFalse((root/'store').exists())


if __name__ == '__main__': unittest.main()
