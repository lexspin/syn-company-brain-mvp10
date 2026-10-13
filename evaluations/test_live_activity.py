import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import live_activity as activity


class LiveActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'data').mkdir()
        self.now = datetime.now(timezone.utc)
        self.stamp = self.now.isoformat()
        self.state = dict(root=str(self.root), objects=[], _view=dict(asof=self.stamp, stale_after_seconds=30))
        self.details = dict(runs={}, traces={}, messages={'main': [{'text': 'PRIVATE_PROMPT'}]},
                            _view=dict(asof=self.stamp, stale_after_seconds=30))
        self.native = []
        self.reader = patch.object(activity, '_native_rows', lambda root: self.native)
        self.reader.start()

    def tearDown(self):
        self.reader.stop()
        self.temp.cleanup()

    def record(self, kind, ident, data=None):
        row = dict(kind=kind, id=ident, version=1, archived=False, updated=self.stamp,
                   data=data or dict(name=ident))
        self.state['objects'].append(row)
        return row

    def request(self, ident, status='running', updated=None):
        return self.record('memory', ident, dict(name='Workflow request', type='native-work-request',
            request_state=status, claimed_at=updated or self.stamp, loop_id='loop', result_ref='',
            request_input='PRIVATE_PROMPT', content='PRIVATE_PROMPT', refs=[]))

    def make_run(self, ident='run1', status='running', updated=None, attempts=None):
        row = dict(id=ident, state=status, updated=updated or self.stamp, loop_id='loop',
            snapshot=dict(loop=dict(data=dict(name='Workflow run', steps=[
                dict(agent='agent', skill='skill', tool='draft', instruction='PRIVATE_PROMPT')])),
                agents={'agent': dict(data=dict(instructions='PRIVATE_PROMPT'))}),
            attempts=attempts or [], outputs=[], error='PRIVATE_PROMPT')
        self.details['runs'][ident] = row
        return row

    def event(self, ident='native1', status='running'):
        row = dict(task_id=ident, title='Explicit native task', status=status,
                   updated_at=self.stamp, lease_expires_at=(self.now + timedelta(seconds=90)).isoformat(),
                   last_event_id=ident+'-e1', area_refs=[], edges=[], outputs=[], summary='PRIVATE_PROMPT')
        self.native.append(row)
        return row

    def view(self):
        for name, value in [('state', self.state), ('details', self.details)]:
            (self.root / 'data' / (name+'.json')).write_text(json.dumps(value), encoding='utf-8')
        return activity.activity_view(self.root)

    def test_output_metadata_is_explicit_bounded_and_safe(self):
        typed = dict(label='Checked edit', reference='C:/code.py', kind='code', action='updated',
                     version='sha256:abc', summary='Scoped fix', start_line=3, end_line=5)
        row = self.event()
        row['outputs'] = [typed, dict(label='SKILL.md', reference='C:/SKILL.md'),
                          dict(label='Bad', reference='https://[malformed'),
                          dict(label='Bad', reference='javascript:alert(1)'),
                          dict(label='Bad', reference='data:text/plain,secret'),
                          dict(label='Bad', reference='https://user:password@example.com'),
                          dict(label='Safe', reference='https://example.com/report')]
        projected = self.view()['tasks'][0]['outputs']
        self.assertEqual(projected[0], dict(typed, url=''))
        self.assertEqual(len(projected), 3)
        self.assertNotIn('kind', projected[1])
        self.assertNotIn('action', projected[1])
        self.assertEqual(projected[2]['url'], 'https://example.com/report')
        damaged = activity._output(dict(typed, kind=[], action='executed', version='x'*161,
                                        summary={'private': 'PRIVATE_PROMPT'}, start_line=True))
        for field in ('kind', 'action', 'version', 'summary', 'start_line', 'end_line'):
            self.assertNotIn(field, damaged)

    def test_twenty_concurrent_native_requests_and_events(self):
        self.record('loop', 'loop')
        for i in range(20):
            self.request('request'+str(i))
            self.event('task'+str(i))
        result = self.view()
        self.assertEqual(len(result['tasks']), 40)
        self.assertTrue(all(t['status'] == 'running' for t in result['tasks']))
        self.assertEqual(len({t['id'] for t in result['tasks']}), 40)

    def test_publication_staleness_does_not_hide_terminal_results(self):
        old = (self.now - timedelta(hours=1)).isoformat()
        self.state['_view']['asof'] = self.details['_view']['asof'] = old
        for state in ['running', 'completed', 'failed']:
            self.request(state, state)
            self.make_run(state, state)
        result = self.view()
        self.assertTrue(result['stale'])
        self.assertEqual({t['status'] for t in result['tasks']}, {'unknown', 'completed', 'failed'})

    def test_failed_request_explains_changed_bindings_without_claiming_resolution(self):
        result = self.record('memory', 'followup', dict(name='Failure archive', status='candidate'))
        request = self.request('failed', 'failed')
        reason = 'Original source bindings changed before claim: file:app/operating_policy.py. Fresh current review required; no workflow effects executed.'
        request['data'].update(failure_reason=reason, result_ref=result['id'])
        task = next(t for t in self.view()['tasks'] if t['id'] == 'request:failed')
        self.assertEqual(task['status'], 'failed')
        self.assertEqual(task['failure_reason'], reason)
        self.assertEqual(task['status_note'], reason)
        self.assertEqual(task['outputs'][0]['label'], 'Recorded result')

    def test_failure_reason_is_bounded_and_not_inferred_from_private_error(self):
        self.request('failed', 'failed')['data']['failure_reason'] = 'Cause\n' + 'x' * 900
        self.make_run('backend', 'failed')['error'] = 'PRIVATE_PROMPT'
        tasks = {t['id']: t for t in self.view()['tasks']}
        self.assertLessEqual(len(tasks['request:failed']['failure_reason']), 600)
        self.assertNotIn('\n', tasks['request:failed']['failure_reason'])
        self.assertIsNone(tasks['run:backend']['failure_reason'])
        self.assertNotIn('PRIVATE_PROMPT', json.dumps(tasks))

    def test_old_individual_running_record_is_unknown_even_with_fresh_publication(self):
        old = (self.now - timedelta(seconds=301)).isoformat()
        self.request('old', updated=old)
        self.make_run(updated=old)
        self.assertTrue(all(t['status'] == 'unknown' for t in self.view()['tasks']))

    def test_explicit_native_lease_is_enforced(self):
        self.event('fresh')
        self.event('expired')['lease_expires_at'] = (self.now-timedelta(seconds=1)).isoformat()
        self.event('terminal', 'completed')['lease_expires_at'] = (self.now-timedelta(hours=1)).isoformat()
        result = {t['id']: t for t in self.view()['tasks']}
        self.assertEqual(result['native:fresh']['status'], 'running')
        self.assertEqual(result['native:expired']['status'], 'unknown')
        self.assertEqual(result['native:terminal']['status'], 'completed')

    def test_registry_and_worker_busy_do_not_fabricate_activity(self):
        self.record('agent', 'agent', dict(name='Agent', parent='boss', skills=['skill']))
        self.record('skill', 'skill')
        self.record('loop', 'loop', dict(name='Loop', steps=[dict(agent='agent', skill='skill')]))
        self.state['worker_busy'] = True
        self.assertEqual(self.view()['tasks'], [])

    def test_snapshot_assignment_is_context_until_attempt(self):
        self.record('agent', 'agent')
        self.record('skill', 'skill')
        run = self.make_run()
        task = self.view()['tasks'][0]
        self.assertIsNone(task['agent_id'])
        self.assertFalse(any(n['kind'] == 'skill' for n in task['nodes']))
        run['attempts'] = [dict(id='a1', step=0, state='running')]
        task = self.view()['tasks'][0]
        self.assertEqual(task['agent_id'], 'agent')
        self.assertEqual(next(n for n in task['nodes'] if n['id'] == 'skill:skill')['usage'], 'observed')

    def test_unknown_references_do_not_fabricate_nodes_or_edges(self):
        row = self.event()
        row['area_refs'] = ['agent:missing']
        row['edges'] = [dict(source='agent:missing', target='memory:missing', relation='uses', provenance='event')]
        task = self.view()['tasks'][0]
        self.assertEqual(len(task['nodes']), 1)
        self.assertEqual(task['edges'], [])
        self.assertTrue(any('unresolved' in s for s in self.view()['coverage']))

    def test_linked_context_does_not_become_execution_flow(self):
        self.record('skill', 'skill')
        self.request('r')['data']['refs'] = ['skill:skill']
        task = self.view()['tasks'][0]
        self.assertEqual(next(n for n in task['nodes'] if n['kind'] == 'skill')['usage'], 'context')
        self.assertFalse(any(e['target'] == 'skill:skill' for e in task['edges']))

    def test_explicit_edge_requires_provenance_and_known_endpoints(self):
        self.record('agent', 'agent')
        self.record('skill', 'skill')
        row = self.event()
        row['edges'] = [dict(source='agent:agent', target='skill:skill', relation='used', provenance='actual-event')]
        result = self.view()['tasks'][0]
        self.assertIsNone(result['edges'][0]['evidence_id'], 'Legacy retained edge must not invent source event')
        row['edges_event_id'] = 'actual-event'
        self.assertEqual(self.view()['tasks'][0]['edges'][0]['evidence_id'], 'actual-event')
        row['edges'][0].pop('provenance')
        self.assertEqual(self.view()['tasks'][0]['edges'], [])

    def test_explicit_public_summary_only(self):
        self.event()['public_summary'] = 'Checking the saved document'
        self.assertEqual(self.view()['tasks'][0]['summary'], 'Checking the saved document')

    def test_heartbeat_does_not_repeat_previous_action_summary(self):
        row = self.event()
        row.update(public_summary='Checking the saved document',
                   last_event_public_summary='Checking the saved document', last_event_type='step')
        self.assertEqual(self.view()['tasks'][0]['event_summary'], 'Checking the saved document')
        row.update(last_event_public_summary='', last_event_type='heartbeat', last_event_id='native1-heartbeat')
        task = self.view()['tasks'][0]
        self.assertEqual(task['summary'], 'Checking the saved document')
        self.assertEqual(task['event_summary'], '')

    def test_recorded_skills_remain_observed_after_heartbeat_and_completion(self):
        self.record('agent', 'agent'); self.record('skill', 'skill')
        edge = dict(source='agent:agent', target='skill:skill', relation='used', provenance='actual-event')
        row = self.event()
        row.update(edges=[edge], edges_event_id='original-edge', last_event_edges=[edge], last_event_type='step')
        for status, kind, latest, expected_motion in [
                ('running', 'step', [edge], True), ('running', 'heartbeat', [], False),
                ('completed', 'completed', [], False)]:
            with self.subTest(kind=kind):
                row.update(status=status, last_event_type=kind, last_event_edges=latest)
                task = self.view()['tasks'][0]
                self.assertEqual(next(n for n in task['nodes'] if n['id']=='skill:skill')['usage'], 'observed')
                self.assertEqual(task['edges'][0]['animate'], expected_motion)

    def test_prompt_message_and_output_bodies_never_leave_projection(self):
        self.request('r')
        run = self.make_run(attempts=[dict(step=0, output='PRIVATE_PROMPT')])
        run['outputs'] = [dict(path='deliverables/run1/01.md', text='PRIVATE_PROMPT')]
        self.event()
        self.details['traces'] = {'main': [dict(id='t', state='completed', updated=self.stamp,
            request='PRIVATE_PROMPT', contract=dict(task='PRIVATE_PROMPT'), execution=[], attempts=[])]}
        self.assertNotIn('PRIVATE_PROMPT', json.dumps(self.view()))

    def test_trace_selection_requires_execution_receipt(self):
        self.record('agent', 'agent')
        trace = dict(id='t', state='completed', updated=self.stamp, selected_agent='agent', execution=[], attempts=[])
        self.details['traces'] = {'main': [trace]}
        self.assertIsNone(self.view()['tasks'][0]['agent_id'])
        trace['execution'] = [dict(attempt_id='receipt')]
        self.assertEqual(self.view()['tasks'][0]['agent_id'], 'agent')

    def test_mismatched_publications_are_unknown(self):
        self.details['_view']['asof'] = (self.now-timedelta(seconds=1)).isoformat()
        self.make_run()
        result = self.view()
        self.assertTrue(result['stale'])
        self.assertEqual(result['tasks'][0]['status'], 'unknown')

    def test_task_cap_keeps_active_tasks(self):
        for i in range(520):
            self.make_run('done'+str(i), 'completed')
        self.make_run('active')
        result = self.view()
        self.assertEqual(len(result['tasks']), activity.MAX_TASKS)
        self.assertEqual(result['tasks'][0]['id'], 'run:active')
        self.assertTrue(any('capped' in s for s in result['coverage']))

    def test_safe_outputs_only_and_event_revision(self):
        row = self.event()
        row['outputs'] = [dict(label='Unsafe', reference='javascript:alert(1)'),
                          dict(label='Private path', reference='C:/private/secret.txt'),
                          dict(label='External receipt', reference='https://example.org/receipt')]
        task = self.view()['tasks'][0]
        self.assertEqual(len(task['outputs']), 2)
        self.assertEqual(task['outputs'][0]['url'], '')
        self.assertEqual(task['outputs'][0]['reference'], 'C:/private/secret.txt')
        self.assertEqual(task['evidence_id'], 'native1-e1')
        row['last_event_id'] = 'native1-e2'
        self.assertEqual(self.view()['tasks'][0]['evidence_id'], 'native1-e2')

    def test_missing_source_reports_gap_and_creates_no_files(self):
        result = activity.activity_view(self.root)
        self.assertTrue(result['stale'])
        self.assertIsNone(result['asof'])
        self.assertEqual(result['tasks'], [])
        self.assertEqual(list((self.root/'data').iterdir()), [])

    def test_only_latest_explicit_event_edges_animate(self):
        self.record('agent', 'agent')
        self.record('skill', 'skill')
        row = self.event()
        edge = dict(source='agent:agent', target='skill:skill', relation='used', provenance='event')
        row.update(edges=[edge], edges_event_id='original-edge', last_event_edges=[edge], last_event_type='step')
        self.assertTrue(self.view()['tasks'][0]['edges'][0]['animate'])
        row.update(last_event_edges=[], last_event_type='heartbeat', last_event_id='native1-e2')
        self.assertFalse(self.view()['tasks'][0]['edges'][0]['animate'])
        self.assertFalse(any(n.get('active') for n in self.view()['tasks'][0]['nodes']))
        self.assertEqual(self.view()['tasks'][0]['edges'][0]['evidence_id'], 'original-edge')
        row.update(status='completed', last_event_edges=[edge], last_event_type='completed')
        self.assertFalse(self.view()['tasks'][0]['edges'][0]['animate'])

    def test_native_orchestration_reads_and_plans_are_distinct(self):
        self.record('skill', 'source')
        self.record('skill', 'target')
        parent = self.event('parent')
        child = self.event('child')
        child.update(parent_task_id='parent', model='gpt-6.1-sol', reasoning_effort='medium',
                     reads=[dict(label='Public source', reference='https://example.org/paper', version='v2', content='PRIVATE_PROMPT'),
                            dict(label='Unsafe', reference='javascript:alert(1)'),
                            dict(label='Credential', reference='https://secret:password@example.org/')])
        edge = dict(source='skill:source', target='skill:target', relation='depends on', provenance='declared prerequisite', observation='dependency')
        child.update(edges=[edge], last_event_edges=[edge], last_event_type='step')
        task = next(t for t in self.view()['tasks'] if t['id'] == 'native:child')
        self.assertEqual(task['parent_task_id'], 'native:parent')
        self.assertEqual(task['model'], 'gpt-6.1-sol')
        self.assertEqual(len(task['reads']), 1)
        self.assertEqual(task['reads'][0]['version'], 'v2')
        self.assertNotIn('PRIVATE_PROMPT', json.dumps(task))
        self.assertFalse(any(e['animate'] for e in task['edges']))
        self.assertTrue(all(n['usage'] == 'context' for n in task['nodes'] if n['kind'] == 'skill'))
        edge['observation'] = 'observed'
        task = next(t for t in self.view()['tasks'] if t['id'] == 'native:child')
        self.assertTrue(any(e['animate'] for e in task['edges']))

    def test_read_only_existing_files_unchanged(self):
        self.view()
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        activity.activity_view(self.root)
        after = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_same_endpoints_keep_each_edges_observation(self):
        self.record('skill', 'source'); self.record('skill', 'target')
        row = self.event()
        for second_relation in ['depends on', 'uses']:
            with self.subTest(second_relation=second_relation):
                observed = dict(source='skill:source', target='skill:target', relation='uses',
                                provenance='actual call', observation='observed')
                planned = dict(observed, relation=second_relation, observation='planned')
                row.update(edges=[observed, planned], last_event_edges=[observed, planned],
                           edges_event_id='pair-event', last_event_type='step')
                edges = self.view()['tasks'][0]['edges']
                self.assertEqual(len(edges), 2)
                self.assertEqual([(e['observation'], e['animate']) for e in edges],
                                 [('observed', True), ('planned', False)])
                self.assertTrue(all(e['evidence_id'] == 'pair-event' for e in edges))

    def test_native_reader_failure_preserves_backend(self):
        self.make_run()
        with patch.object(activity, '_native_rows', side_effect=ValueError('invalid')):
            result = self.view()
        self.assertEqual(result['tasks'][0]['id'], 'run:run1')
        self.assertTrue(any('reader failed' in s for s in result['coverage']))

    def history_reader(self, history):
        return SimpleNamespace(read_events=lambda root, task_id, limit: history)

    def test_event_history_preserves_authentic_commit_order_and_whitelists_fields(self):
        events = [dict(event_id='event-z', type='started', at=self.stamp,
                       summary='Started scoped work', provenance='chat:event', prompt='PRIVATE_PROMPT'),
                  dict(event_id='event-a', type='step', at=self.stamp,
                       edges=[dict(source='agent:agent', target='skill:skill', relation='used', provenance='tool receipt')]),
                  dict(event_id='event-b', type='completed', at=self.stamp,
                       outputs=[dict(label='Working document', reference='D:/AgentWork/project/output.md')])]
        with patch.object(activity, '_native_reader', return_value=self.history_reader(dict(events=events, truncated=False))):
            result = activity.event_history(self.root, 'task1')
        self.assertEqual([e['event_id'] for e in result['events']], ['event-z', 'event-a', 'event-b'])
        self.assertEqual(result['events'][2]['outputs'][0]['reference'], 'D:/AgentWork/project/output.md')
        self.assertNotIn('PRIVATE_PROMPT', json.dumps(result))
        self.assertFalse(result['truncated'])

    def test_event_history_bounds_and_invalid_identity(self):
        events = [dict(event_id='event-'+str(i), type='heartbeat', at=self.stamp, summary='x'*1000) for i in range(120)]
        with patch.object(activity, '_native_reader', return_value=self.history_reader(dict(events=events, truncated=True))):
            result = activity.event_history(self.root, 'task1')
        self.assertEqual(len(result['events']), 100)
        self.assertEqual(result['events'][0]['event_id'], 'event-20')
        self.assertTrue(result['truncated'])
        self.assertLessEqual(len(result['events'][0]['summary']), 600)
        with self.assertRaises(ValueError):
            activity.event_history(self.root, '../bad task')

    def test_event_history_preserves_only_explicit_bounded_area_refs(self):
        events = [dict(event_id='areas', type='step', at=self.stamp,
                       area_refs=['project:company-brain', 'skill:interface-audit', None, '<script>'],
                       edges=[]),
                  dict(event_id='legacy', type='step', at=self.stamp,
                       project_id='unreported-project',
                       edges=[dict(source='skill:planned', target='project:planned', observation='planned')]),
                  dict(event_id='bounded', type='step', at=self.stamp,
                       area_refs=['skill:area-'+str(i) for i in range(40)])]
        with patch.object(activity, '_native_reader', return_value=self.history_reader(dict(events=events))):
            result = activity.event_history(self.root, 'task1')['events']
        self.assertEqual(result[0]['area_refs'], ['project:company-brain', 'skill:interface-audit'])
        self.assertEqual(result[0]['edges'], [])
        self.assertEqual(result[1]['area_refs'], [])
        self.assertEqual(result[2]['area_refs'], ['skill:area-'+str(i) for i in range(32)])

    def test_event_history_preserves_reported_loop_without_inferred_hops(self):
        hops = [('agent:agent', 'skill:skill'), ('skill:skill', 'agent:agent'), ('agent:agent', 'skill:skill')]
        events = [dict(event_id='loop-'+str(i), type='step', at=self.stamp,
                       edges=[dict(source=source, target=target, relation='used', provenance='actual receipt')])
                  for i, (source, target) in enumerate(hops)]
        with patch.object(activity, '_native_reader', return_value=self.history_reader(dict(events=events, truncated=False))):
            result = activity.event_history(self.root, 'task1')
        self.assertEqual([(e['edges'][0]['source'], e['edges'][0]['target']) for e in result['events']], hops)
        self.assertEqual(len(result['events']), 3)

    def test_event_history_missing_or_failed_reader_reports_gap(self):
        with patch.object(activity, '_native_reader', return_value=None):
            result = activity.event_history(self.root, 'task1')
        self.assertEqual(result['events'], [])
        self.assertTrue(result['coverage'])
        with patch.object(activity, '_native_reader', side_effect=ValueError('invalid reader')):
            self.assertTrue(activity.event_history(self.root, 'task1')['coverage'])


if __name__ == '__main__':
    unittest.main()
