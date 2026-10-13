"""Gateway copy: pure admission and standalone routine contracts.
Canonical command/Brain integration is tested in V2/evaluations/test_operating_policy.py;
the gateway forwards state mutations to V2 and is not a second writer.
"""
import json
import sys
import tempfile
import subprocess
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
from operating_policy import interpret, require_allowed, policy_for_root, admit_command
from routine_engine import RoutineEngine, rows


def record(state='active', batch=2):
    return {'kind': 'stack', 'id': 'operating-policy', 'version': 1, 'archived': False,
            'data': {'name': 'Operating policy', 'schema_version': 1, 'requested_state': state,
                     'idle': {'max_batch': batch, 'cooldown_seconds': 300}, 'refs': []}}


class PolicyTests(unittest.TestCase):
    def test_legacy_migration_and_fail_closed(self):
        self.assertEqual(interpret(None)['effective_state'], 'active')
        self.assertEqual(interpret(None, previously_configured=True)['effective_state'], 'off')
        for broken in ({'data': {}}, record() | {'archived': True}, record() | {'data': {'schema_version': 1, 'requested_state': 'unknown'}}):
            with self.assertRaises(ValueError): require_allowed(interpret(broken), 'routine')

    def test_off_idle_active_are_admission_not_effort(self):
        for kind in ('routine', 'task'):
            with self.assertRaises(ValueError): require_allowed(interpret(record('off')), kind)
        self.assertEqual(require_allowed(interpret(record('idle')), 'routine'), 'idle')
        with self.assertRaises(ValueError): require_allowed(interpret(record('idle')), 'task')
        self.assertEqual(require_allowed(interpret(record()), 'task'), 'active')
        self.assertNotIn('reasoning_effort', interpret(record()))

    def test_agent_override_cannot_raise_global_state(self):
        with self.assertRaises(ValueError): require_allowed(interpret(record('idle')), 'task', {'operating_state': 'active'})
        with self.assertRaises(ValueError): require_allowed(interpret(record()), 'routine', {'operating_state': 'off'})

    def test_scheduled_requires_global_idle_and_agent_permission(self):
        for state in ('off', 'active'):
            for agent in (None, {'operating_state': 'idle'}, {'operating_state': 'active'}):
                with self.assertRaises(ValueError): require_allowed(interpret(record(state)), 'scheduled', agent)
        for agent in (None, {'operating_state': 'active'}, {'operating_state': 'idle'}):
            self.assertEqual(require_allowed(interpret(record('idle')), 'scheduled', agent), 'idle')
        for agent in ({'operating_state': 'off'}, {'operating_state': 'invalid'}):
            with self.assertRaises(ValueError): require_allowed(interpret(record('idle')), 'scheduled', agent)
        with self.assertRaises(ValueError): require_allowed(interpret({'data': {}}), 'scheduled')
        self.assertEqual(require_allowed(interpret(record('active')), 'routine'), 'active')


    def test_off_preserves_control_and_completed_reconciliation(self):
        class Fake:
            root = Path('/nonexistent-policy-test')
            def get(self, kind, id): return record('off')
        brain = Fake()
        admit_command(brain, 'operating-state', {})
        admit_command(brain, 'cancel', {})
        admit_command(brain, 'save', {'kind': 'memory', 'data': {'type': 'native-work-request', 'request_state': 'completed'}})
        with self.assertRaises(ValueError): admit_command(brain, 'creative-generate', {'maintenance': {'request_id': 'x', 'claimant': 'x'}})
        with self.assertRaises(ValueError): admit_command(brain, 'start', {})




class RoutinePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'runtime')
        self.root = Path(self.temp.name)
        (self.root/'routines').mkdir(); (self.root/'data').mkdir()
        routine = {'id': 'digest', 'name': 'Briefing', 'machine': 'local', 'kind': 'morning-digest', 'schedule': '08:00',
                   'max_turns': 0, 'timeout_seconds': 30, 'output': 'deliverables/briefs'}
        config = {'machine_id': 'local', 'timezone': 'UTC', 'poll_seconds': 300,
                  'caps': {'daily_runs': 12, 'window_minutes': 60, 'window_runs': 4}, 'routines': [routine]}
        (self.root/'routines/registry.json').write_text(json.dumps(config))
        self.now = datetime(2026, 10, 11, 9, tzinfo=timezone.utc)
        self.policy('idle'); self.engine = RoutineEngine(self.root)

    def tearDown(self): self.temp.cleanup()
    def policy(self, state):
        (self.root/'data/state.json').write_text(json.dumps({'objects': [record(state, 1)], 'runs': []}))
    def tick(self):
        with patch('routine_engine.local_clock', side_effect=lambda value, zone: value): return self.engine.tick(self.now)

    def test_off_does_not_admit_or_consume_due_occurrence(self):
        self.policy('off')
        with patch.object(self.engine, 'execute') as execute:
            self.assertEqual(self.tick()['admission'], 'off'); execute.assert_not_called()
        self.assertEqual(rows(self.engine.events), [])
        with self.assertRaises(ValueError): self.engine.request_run('digest', 'owner-request-001')
        self.policy('idle'); self.tick(); self.assertEqual(len(self.engine.messages()), 1)

    def test_idle_batch_cooldown_and_identity(self):
        self.engine.request_run('digest', 'owner-request-001')
        self.tick(); self.tick(); self.assertEqual(len(self.engine.messages()), 1)
        self.now += timedelta(seconds=300)
        self.tick(); self.tick(); self.assertEqual(len(self.engine.messages()), 2)
        self.assertEqual(len([row for row in rows(self.engine.events) if row['status'] == 'started']), 2)

    def test_active_defers_automatic_occurrence_but_runs_explicit_request(self):
        self.policy('active')
        with patch.object(self.engine, 'execute') as execute:
            self.tick(); execute.assert_not_called()
        self.assertEqual(rows(self.engine.events), [])
        self.engine.request_run('digest', 'owner-request-001')
        self.tick(); self.tick()
        self.assertEqual(len(self.engine.messages()), 1)
        self.assertEqual(self.engine.messages()[0]['occurrence'], 'manual:owner-request-001')
        self.policy('idle'); self.now += timedelta(seconds=300)
        self.tick(); self.tick()
        self.assertEqual(len(self.engine.messages()), 2)
        self.assertEqual(self.engine.messages()[1]['occurrence'], 'digest:2026-10-11')

    def test_state_change_before_effect_does_not_consume_scheduled_occurrence(self):
        for blocked in ('off', 'active'):
            with self.subTest(state=blocked):
                self.policy('idle')
                with patch('operating_policy.policy_for_root', side_effect=[interpret(record('idle')), interpret(record('idle')), interpret(record(blocked)), interpret(record(blocked))]), patch.object(self.engine, 'execute') as execute:
                    self.tick(); execute.assert_not_called()
                self.assertEqual(rows(self.engine.events), [])

    def test_off_reconciles_begun_occurrence_and_preserves_manual_queue(self):
        from routine_engine import append
        self.engine.request_run('digest', 'owner-request-001')
        append(self.engine.events, {'routine': 'digest', 'occurrence': 'digest:2026-10-11', 'status': 'started', 'time': self.now.isoformat()})
        self.policy('off')
        with patch.object(self.engine, 'execute') as execute:
            self.tick(); execute.assert_not_called()
        self.assertEqual(rows(self.engine.events)[-1]['status'], 'interrupted')
        self.assertTrue((self.engine.queue/'owner-request-001.json').exists())
        self.policy('idle'); self.now += timedelta(seconds=300)
        self.tick(); self.tick()
        self.assertEqual(len(self.engine.messages()), 1)
        self.assertEqual(self.engine.messages()[0]['occurrence'], 'manual:owner-request-001')

    def test_scheduled_cli_only_idle_without_state_changes(self):
        script = Path(__file__).resolve().parents[1]/'app/operating_policy.py'
        for state in ('off', 'idle', 'active'):
            self.policy(state)
            before = (self.root/'data/state.json').read_bytes()
            result = subprocess.run([sys.executable, '-B', str(script), '--root', str(self.root), '--lane', 'scheduled'], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0 if state == 'idle' else 3)
            self.assertEqual(json.loads(result.stdout)['allowed'], state == 'idle')
            self.assertEqual((self.root/'data/state.json').read_bytes(), before)

    def test_uncertain_occurrence_is_not_replayed(self):
        from routine_engine import append
        append(self.engine.events, {'routine': 'digest', 'occurrence': 'digest:2026-10-11', 'status': 'started', 'time': self.now.isoformat()})
        with patch.object(self.engine, 'execute') as execute:
            self.tick(); execute.assert_not_called()
        self.assertEqual(rows(self.engine.events)[-1]['status'], 'interrupted')

    def test_policy_read_failure_blocks_execution(self):
        (self.root/'data/state.json').write_text('{bad')
        self.assertEqual(policy_for_root(self.root)['effective_state'], 'off')
        with patch.object(self.engine, 'execute') as execute:
            self.tick(); execute.assert_not_called()

    def test_native_cli_skips_not_due_and_unchanged_without_writes(self):
        script = Path(__file__).resolve().parents[1]/'app/operating_policy.py'
        base = [sys.executable, str(script), '--root', str(self.root), '--lane', 'routine']
        before = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob('*') if p.is_file())
        for extra in (['--due-at', '2099-01-01T00:00:00+00:00'], ['--unchanged-evidence']):
            result = subprocess.run(base+extra, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 3)
            decision = json.loads(result.stdout)
            self.assertFalse(decision['allowed']); self.assertEqual(decision['effective_state'], 'idle')
        self.assertEqual(before, sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob('*') if p.is_file()))


if __name__ == '__main__': unittest.main()
