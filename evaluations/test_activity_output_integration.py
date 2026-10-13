"""Actual checked callbacks → native store → public projection/history.

Only dynamic fixture-root module discovery is adapted; reporting, SQLite reads,
callback checks and public projections all use their real implementations.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
import live_activity
import native_activity
from native_execution import NativeExecution


class ActivityOutputIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'runtime')
        self.root = Path(self.temp.name)
        (self.root / 'data').mkdir()
        self.document = self.root / 'result.md'
        self.code = self.root / 'result.py'
        self.source = self.root / 'source.md'
        self.source.write_text('Checked fixture source.', encoding='utf-8')
        stamp = datetime.now(timezone.utc).isoformat()
        record = lambda kind, ident: dict(kind=kind, id=ident, version=1, archived=False,
                                         updated=stamp, data={'name': ident})
        state = dict(root=str(self.root), _view={'asof': stamp, 'stale_after_seconds': 30},
                     objects=[record('project', 'fixture'), record('skill', 'author'),
                              record('skill', 'checker')])
        details = dict(root=str(self.root), _view={'asof': stamp, 'stale_after_seconds': 30},
                       runs={}, traces={}, messages={})
        for name, data in [('state', state), ('details', details)]:
            (self.root / 'data' / (name + '.json')).write_text(json.dumps(data), encoding='utf-8')
        self.reader = patch.object(live_activity, '_native_reader', return_value=native_activity)
        self.reader.start()

    def tearDown(self):
        self.reader.stop()
        self.temp.cleanup()

    def projected(self, task_id):
        return next(row for row in live_activity.activity_view(self.root)['tasks']
                    if row['id'] == 'native:' + task_id)

    def outputs(self):
        return [dict(label='Checked document', reference=str(self.document), kind='document',
                     action='created', version='fixture-v1', summary='Retained checked fixture document',
                     start_line=1, end_line=2),
                dict(label='Checked code', reference=str(self.code), kind='code',
                     action='created', start_line=1, end_line=1)]

    def write_and_read_actual_outputs(self):
        self.document.write_text('Checked fixture source.\nActual result.\n', encoding='utf-8')
        self.code.write_text('answer = 42\n', encoding='utf-8')
        return (self.source.read_text(encoding='utf-8'),
                self.document.read_text(encoding='utf-8'), self.code.read_text(encoding='utf-8'))

    def test_checked_artifacts_keep_typed_identity_through_projection_and_history(self):
        output_metadata = self.outputs()
        edges = [dict(source='skill:author', target='skill:checker', relation='checked by',
                      provenance='Actual fixture callback and returned check', observation='observed'),
                 dict(source='project:fixture', target='skill:author', relation='configured dependency',
                      provenance='Fixture configured relationship only', observation='dependency')]
        with NativeExecution(self.root, 'actual-output', 'Checked artifact fixture',
                             chat_id='integration-fixture', project_id='fixture') as run:
            result = run.stage('write-artifacts', 'Write and read the actual fixture artifacts',
                self.write_and_read_actual_outputs,
                check=lambda value: value[0] in value[1] and compile(value[2], str(self.code), 'exec') is not None,
                reads=[dict(label='Actual source', reference=str(self.source), version='1')],
                edges=edges, outputs=output_metadata)
            task = self.projected('actual-output')
            self.assertEqual(task['status'], 'running')
            for actual, expected in zip(task['outputs'], output_metadata):
                self.assertEqual({key: actual[key] for key in expected}, expected)
                self.assertEqual(actual['url'], '')  # Local file paths remain inert references.
            self.assertFalse(any(edge['animate'] for edge in task['edges']
                                 if edge.get('observation') == 'dependency'))
            run.accept('accept', 'Read back the checked artifacts',
                       lambda: self.document.read_text(encoding='utf-8') == result[1]
                               and self.code.read_text(encoding='utf-8') == result[2],
                       requires=('write-artifacts',))
            run.complete('Actual fixture artifacts checked')
        raw = native_activity.read_events(self.root, 'actual-output')['events']
        public = live_activity.event_history(self.root, 'actual-output')
        self.assertEqual([row['event_id'] for row in public['events']], [row['event_id'] for row in raw])
        returned = next(row for row in public['events'] if row['event_id'].endswith(':write-artifacts:returned'))
        self.assertEqual(len(returned['outputs']), len(output_metadata))
        for actual, expected in zip(returned['outputs'], output_metadata):
            self.assertEqual({key: actual[key] for key in expected}, expected)
            self.assertEqual(actual['url'], '')
        self.assertEqual(returned['reads'][0]['reference'], str(self.source))
        self.assertEqual(returned['reads'][0]['version'], '1')
        final = self.projected('actual-output')
        self.assertEqual(final['status'], 'completed')
        self.assertFalse(any(edge['animate'] for edge in final['edges']))
        self.assertFalse(any(node['active'] for node in final['nodes']))
        self.assertNotIn('answer = 42', json.dumps(public))
        self.assertNotIn('Actual result.', json.dumps(public))

    def test_area_only_callback_survives_real_store_reader_and_history(self):
        # Exercise the actual dynamic reader too; no mocked layer may supply refs.
        self.reader.stop()
        (self.root / 'app').mkdir()
        (self.root / 'app/native_activity.py').write_bytes((ROOT / 'app/native_activity.py').read_bytes())
        areas = ['project:fixture', 'skill:author']
        with NativeExecution(self.root, 'actual-areas', 'Read area fixture',
                             chat_id='integration-fixture') as run:
            run.stage('read', 'Read actual fixture source',
                      lambda: self.source.read_text(encoding='utf-8'),
                      check=lambda value: value == 'Checked fixture source.', area_refs=areas)
            raw = native_activity.read_events(self.root, 'actual-areas')['events']
            public = live_activity.event_history(self.root, 'actual-areas')['events']
            for events in (raw, public):
                returned = next(e for e in events if e['event_id'].endswith(':read:returned'))
                self.assertEqual(returned['area_refs'], areas)
                self.assertEqual(returned['edges'], [])
                self.assertEqual(events[0]['area_refs'], [])
            run.accept('check', 'Recheck fixture source',
                       lambda: self.source.read_text(encoding='utf-8') == 'Checked fixture source.',
                       requires=('read',))
            run.complete('Area-only read checked')

    def test_failed_actual_check_does_not_publish_declared_artifacts(self):
        with self.assertRaisesRegex(RuntimeError, 'check did not pass'):
            with NativeExecution(self.root, 'failed-output', 'Failed artifact fixture',
                                 chat_id='integration-fixture') as run:
                run.stage('write-artifacts', 'Run a failed actual output check',
                          self.write_and_read_actual_outputs, check=lambda _: False, outputs=self.outputs())
        self.assertTrue(self.document.is_file())  # The callback really ran; acceptance failed.
        self.assertEqual(self.projected('failed-output')['status'], 'failed')
        self.assertEqual(self.projected('failed-output')['outputs'], [])
        history = live_activity.event_history(self.root, 'failed-output')['events']
        self.assertTrue(all(not row['outputs'] for row in history))
        self.assertFalse(any(row['event_id'].endswith(':write-artifacts:returned') for row in history))

    def test_actual_children_preserve_parent_without_sibling_causality(self):
        native_activity.emit_activity(self.root, dict(task_id='coordinator', event_id='coordinator:started',
            type='started', chat_id='integration-fixture', title='Reported coordinator',
            provenance='Actual fixture parent report'))
        for task_id in ('branch-one', 'branch-two'):
            with NativeExecution(self.root, task_id, 'Actual branch fixture',
                                 chat_id='integration-fixture', parent_task_id='coordinator') as run:
                run.stage('read-source', 'Read the fixture source',
                          lambda: self.source.read_text(encoding='utf-8'),
                          check=lambda value: value == 'Checked fixture source.')
                run.accept('accept', 'Check returned fixture source', lambda: True, requires=('read-source',))
                run.complete('Actual branch check returned')
        tasks = [self.projected(task_id) for task_id in ('branch-one', 'branch-two')]
        self.assertEqual([task['parent_task_id'] for task in tasks], ['native:coordinator'] * 2)
        self.assertTrue(all(not task['edges'] for task in tasks))
        self.assertTrue(all(not event['edges'] for task_id in ('branch-one', 'branch-two')
                            for event in live_activity.event_history(self.root, task_id)['events']))


if __name__ == '__main__':
    unittest.main()
