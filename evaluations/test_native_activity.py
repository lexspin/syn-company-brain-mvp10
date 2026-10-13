from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from native_activity import emit_activity, read_activity, read_events, validate_event, main


class NativeActivityTests(unittest.TestCase):
    def test_typed_outputs_roundtrip_and_legacy_preserved(self):
        legacy = dict(label='Older pointer', reference='C:/output.py')
        typed = dict(label='Checked source', reference='C:/output.py', kind='code',
                     action='updated', version='sha256:abc', summary='Scoped fix',
                     start_line=2, end_line=8)
        emit_activity(self.root, self.event(outputs=[legacy, typed]), self.now)
        self.assertEqual(read_activity(self.root, self.now)[0]['outputs'], [legacy, typed])
        self.assertEqual(read_events(self.root, 'one')['events'][0]['outputs'], [legacy, typed])
        self.assertNotIn('kind', read_activity(self.root, self.now)[0]['outputs'][0])

    def test_invalid_output_metadata_rejected_before_commit(self):
        for extra in [dict(kind='inferred-code'), dict(action='executed'), dict(kind=[]),
                      dict(version=''), dict(summary='x'*301), dict(summary='a\nb'),
                      dict(start_line=True), dict(start_line=0), dict(start_line=1000001),
                      dict(end_line=2), dict(start_line=3, end_line=2)]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                emit_activity(self.root, self.event(outputs=[dict(label='Output', reference='C:/x', **extra)]), self.now)
        self.assertEqual(read_events(self.root, 'one')['events'], [])

    def test_accumulated_record_limit_rejects_atomically(self):
        emit_activity(self.root, self.event(), self.now)
        with patch('native_activity.MAX_RECORD_BYTES', 100), self.assertRaisesRegex(ValueError, 'record too large'):
            emit_activity(self.root, self.event(kind='step', summary='Would disappear from bounded reader'), self.now)
        self.assertEqual([e['type'] for e in read_events(self.root, 'one')['events']], ['started'])
        self.assertEqual(read_activity(self.root, self.now)[0]['summary'], '')

    def test_parent_identity_metadata_and_bounded_reads(self):
        emit_activity(self.root, self.event('parent'), self.now)
        emit_activity(self.root, self.event('child', parent_task_id='parent', model='gpt-6.1-sol', reasoning_effort='medium'), self.now)
        reads = [dict(label='Exact source', reference='C:/source.md', version='sha256:abc')]
        edge = dict(source='skill:a', target='project:b', relation='depends-on', provenance='declared prerequisite', observation='dependency')
        emit_activity(self.root, self.event('child', 'step', reads=reads, edges=[edge]), self.now)
        emit_activity(self.root, self.event('child', 'heartbeat'), self.now)
        child = next(r for r in read_activity(self.root, self.now) if r['task_id'] == 'child')
        self.assertEqual(child['parent_task_id'], 'parent')
        self.assertEqual(child['chat_id'], 'chat:child')
        self.assertEqual(child['model'], 'gpt-6.1-sol')
        self.assertEqual(child['reads'], reads)
        self.assertEqual(child['last_event_reads'], [])
        self.assertEqual(child['edges'], [edge])
        self.assertEqual(read_events(self.root, 'child')['events'][1]['reads'], reads)
        for field in ('parent_task_id', 'model', 'reasoning_effort'):
            with self.assertRaisesRegex(ValueError, 'immutable'):
                emit_activity(self.root, self.event('child', 'step', 'new', **{field: 'other'}), self.now)
        with self.assertRaisesRegex(ValueError, 'unknown parent'):
            emit_activity(self.root, self.event('unknown', parent_task_id='missing'), self.now)
        with self.assertRaisesRegex(ValueError, 'itself'):
            emit_activity(self.root, self.event('self', parent_task_id='self'), self.now)

    def test_cycle_in_existing_ancestry_rejected_without_child_commit(self):
        import sqlite3
        emit_activity(self.root, self.event('parent'), self.now)
        # Simulate damaged legacy metadata; normal start-only writes cannot form cycles.
        connection = sqlite3.connect(self.root / 'runtime' / 'native-activity.sqlite')
        try:
            row = connection.execute('SELECT record FROM tasks WHERE task_id=?', ('parent',)).fetchone()
            record = json.loads(row[0]); record['parent_task_id'] = 'parent'
            connection.execute('UPDATE tasks SET record=? WHERE task_id=?', (json.dumps(record), 'parent'))
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(ValueError, 'cycle'):
            emit_activity(self.root, self.event('child', parent_task_id='parent'), self.now)
        self.assertEqual(read_events(self.root, 'child')['events'], [])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime')
        self.root = Path(self.temp.name)
        self.now = datetime(2026, 10, 11, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp.cleanup()

    def event(self, task='one', kind='started', suffix='', **extra):
        result = dict(event_id=f'{task}:{kind}:{suffix}', task_id=task, chat_id=f'chat:{task}', type=kind)
        if kind == 'started':
            result.update(title='Public task', provenance='native-chat:explicit-hook')
        result.update(extra)
        return result

    def test_twenty_concurrent_tasks_and_idempotent_retries(self):
        events = [self.event(str(i)) for i in range(20)]
        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(lambda e: emit_activity(self.root, e, self.now), events))
        self.assertTrue(all(r['accepted'] for r in results))
        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(lambda e: emit_activity(self.root, e, self.now), events * 2))
        self.assertTrue(all(r['duplicate'] for r in results))
        records = read_activity(self.root, self.now)
        self.assertEqual(len(records), 20)
        self.assertEqual(len({r['chat_id'] for r in records}), 20)

    def test_duplicate_mismatch_and_identity_conflict(self):
        first = self.event(); emit_activity(self.root, first, self.now)
        with self.assertRaisesRegex(ValueError, 'different payload'):
            emit_activity(self.root, dict(first, summary='Changed'), self.now)
        with self.assertRaisesRegex(ValueError, 'different chat'):
            emit_activity(self.root, self.event(kind='step', chat_id='chat:other'), self.now)
        self.assertEqual(read_activity(self.root, self.now)[0]['summary'], '')

    def test_terminal_cannot_reopen_and_duplicate_terminal_is_safe(self):
        for terminal in ('completed', 'failed'):
            emit_activity(self.root, self.event(terminal), self.now)
            end = self.event(terminal, terminal)
            emit_activity(self.root, end, self.now)
            self.assertTrue(emit_activity(self.root, end, self.now)['duplicate'])
            for kind in ('started', 'heartbeat', 'step', 'output', 'completed', 'failed'):
                with self.assertRaisesRegex(ValueError, 'terminal'):
                    emit_activity(self.root, self.event(terminal, kind, 'new'), self.now)
        self.assertEqual({r['status'] for r in read_activity(self.root, self.now + timedelta(days=1))}, {'completed', 'failed'})

    def test_stale_lease_and_explicit_heartbeat(self):
        emit_activity(self.root, self.event(), self.now)
        self.assertEqual(read_activity(self.root, self.now + timedelta(seconds=89))[0]['status'], 'running')
        self.assertEqual(read_activity(self.root, self.now + timedelta(seconds=90))[0]['status'], 'stale')
        emit_activity(self.root, self.event(kind='heartbeat'), self.now + timedelta(seconds=100))
        self.assertEqual(read_activity(self.root, self.now + timedelta(seconds=101))[0]['status'], 'running')

    def test_explicit_refs_edges_outputs_and_public_schema(self):
        edges = [{'source': 'skill:a', 'target': 'project:b', 'relation': 'uses', 'provenance': 'explicit native hook'}]
        emit_activity(self.root, self.event(area_refs=['skill:a', 'project:b'], edges=edges), self.now)
        output = {'label': 'Verified result', 'reference': 'C:/Example/result.md'}
        emit_activity(self.root, self.event(kind='output', outputs=[output]), self.now)
        record = read_activity(self.root, self.now)[0]
        self.assertEqual(record['edges'], edges); self.assertEqual(record['outputs'], [output])
        self.assertEqual(record['area_refs'], ['skill:a', 'project:b'])
        self.assertEqual(record['last_event_type'], 'output')
        self.assertEqual(record['last_event_edges'], [])
        self.assertNotIn('prompt', record)
        with self.assertRaisesRegex(ValueError, 'unknown'):
            validate_event(self.event(prompt='private'))

    def test_event_edges_do_not_pulse_retained_relationships(self):
        edge = {'source': 'skill:a', 'target': 'project:b', 'relation': 'uses', 'provenance': 'explicit hook'}
        emit_activity(self.root, self.event(edges=[edge]), self.now)
        self.assertEqual(read_activity(self.root, self.now)[0]['last_event_edges'], [edge])
        original_edge_event_id = self.event()['event_id']
        self.assertEqual(read_activity(self.root, self.now)[0]['edges_event_id'], original_edge_event_id)
        emit_activity(self.root, self.event(kind='heartbeat'), self.now)
        record = read_activity(self.root, self.now)[0]
        self.assertEqual(record['edges'], [edge])
        self.assertEqual(record['last_event_type'], 'heartbeat')
        self.assertEqual(record['last_event_edges'], [])
        self.assertEqual(record['edges_event_id'], original_edge_event_id)
        emit_activity(self.root, self.event(kind='step', suffix='no-edge'), self.now)
        self.assertEqual(read_activity(self.root, self.now)[0]['edges_event_id'], original_edge_event_id)
        emit_activity(self.root, self.event(kind='step', edges=[edge]), self.now)
        self.assertEqual(read_activity(self.root, self.now)[0]['last_event_edges'], [edge])
        self.assertEqual(read_activity(self.root, self.now)[0]['edges_event_id'], self.event(kind='step')['event_id'])

    def test_heartbeat_retains_task_summary_without_claiming_new_action_text(self):
        emit_activity(self.root, self.event(summary='Checking the document'), self.now)
        record = read_activity(self.root, self.now)[0]
        self.assertEqual(record['public_summary'], 'Checking the document')
        self.assertEqual(record['last_event_public_summary'], 'Checking the document')
        emit_activity(self.root, self.event(kind='heartbeat'), self.now)
        record = read_activity(self.root, self.now)[0]
        self.assertEqual(record['public_summary'], 'Checking the document')
        self.assertEqual(record['last_event_public_summary'], '')
        emit_activity(self.root, self.event(kind='step', summary='Document reload passed'), self.now)
        self.assertEqual(read_activity(self.root, self.now)[0]['last_event_public_summary'], 'Document reload passed')

    def test_invalid_events_are_rejected(self):
        invalid = [None, [], {}, {1: 'bad key'}, self.event(type=[]), self.event(type='bogus'), self.event(title=''),
                   self.event(summary='a' * 601), self.event(summary='line\nline'),
                   self.event(lease_seconds=True), self.event(lease_seconds=1), self.event(lease_seconds=301),
                   self.event(area_refs=['x'] * 33), self.event(area_refs=['../bad path']),
                   self.event(edges=[{'source': 'x'}]), self.event(outputs=[{'url': 'http://example.com'}]),
                   self.event(chat_id='chat id'), self.event(provenance='')]
        for event in invalid:
            with self.subTest(event=event), self.assertRaises(ValueError):
                emit_activity(self.root, event, self.now)
        self.assertEqual(read_activity(self.root, self.now), [])

    def test_must_start_and_timestamp_monotonic(self):
        with self.assertRaisesRegex(ValueError, 'begin'):
            emit_activity(self.root, self.event(kind='step'), self.now)
        emit_activity(self.root, self.event(), self.now)
        with self.assertRaisesRegex(ValueError, 'already started'):
            emit_activity(self.root, self.event(suffix='twice'), self.now)
        with self.assertRaisesRegex(ValueError, 'precedes'):
            emit_activity(self.root, self.event(kind='step'), self.now - timedelta(seconds=1))

    def test_reader_does_not_create_store_and_supports_workspace_root(self):
        self.assertEqual(read_activity(self.root), [])
        self.assertFalse((self.root / 'runtime').exists())
        (self.root / 'V2' / 'app').mkdir(parents=True)
        emit_activity(self.root, self.event(), self.now)
        self.assertEqual(read_activity(self.root / 'V2', self.now)[0]['task_id'], 'one')

    def test_cli_json_file_malformed_and_oversized(self):
        path = self.root / 'event.json'
        with patch('builtins.print'):
            path.write_text('{broken', encoding='utf-8')
            self.assertEqual(main(['--root', str(self.root), 'emit', '--json-file', str(path)]), 2)
            path.write_text('x' * 65537, encoding='utf-8')
            self.assertEqual(main(['--root', str(self.root), 'emit', '--json-file', str(path)]), 2)
            path.write_text(json.dumps(self.event()), encoding='utf-8')
            self.assertEqual(main(['--root', str(self.root), 'emit', '--json-file', str(path)]), 0)
            self.assertEqual(main(['--root', str(self.root), 'read']), 0)

    def test_history_bounded_commit_order_and_no_retained_edge_replay(self):
        edge = {'source': 'skill:a', 'target': 'project:b', 'relation': 'uses', 'provenance': 'explicit hook'}
        emit_activity(self.root, self.event(edges=[edge]), self.now)
        emit_activity(self.root, self.event(kind='step', suffix='z', summary='Checked action'), self.now)
        emit_activity(self.root, self.event(kind='heartbeat', suffix='a'), self.now)
        history = read_events(self.root, 'one')
        self.assertFalse(history['truncated'])
        self.assertEqual([e['type'] for e in history['events']], ['started', 'step', 'heartbeat'])
        self.assertEqual(history['events'][0]['edges'], [edge])
        self.assertEqual(history['events'][1]['edges'], [])
        bounded = read_events(self.root, 'one', 2)
        self.assertTrue(bounded['truncated'])
        self.assertEqual([e['type'] for e in bounded['events']], ['step', 'heartbeat'])
        self.assertEqual(read_events(self.root, 'absent'), {'events': [], 'truncated': False})
        for value in (0, True, 501, '2'):
            with self.assertRaises(ValueError): read_events(self.root, 'one', value)

    def test_reader_prioritizes_live_leases_then_latest_and_bounds_results(self):
        emit_activity(self.root, self.event('aaa'), self.now)
        emit_activity(self.root, self.event('bbb'), self.now + timedelta(seconds=10))
        emit_activity(self.root, self.event('bbb', 'completed'), self.now + timedelta(seconds=11))
        self.assertEqual(read_activity(self.root, self.now + timedelta(seconds=20), limit=1)[0]['task_id'], 'aaa')
        self.assertEqual(read_activity(self.root, self.now + timedelta(seconds=100), limit=1)[0]['task_id'], 'bbb')
        for value in (0, True, 2049, '2'):
            with self.assertRaises(ValueError): read_activity(self.root, self.now, limit=value)


if __name__ == '__main__':
    unittest.main()
