from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from native_activity import read_activity, read_events
from native_execution import NativeExecution, AlreadyRecorded, main


class NativeExecutionTests(unittest.TestCase):
    def test_selected_agent_attribution_is_supported_and_validated_without_role_claim(self):
        with self.run_task(agent_id='engineering-manager') as run:
            run.stage('read', 'Actual checked callback', lambda: 1, check=lambda value: value == 1)
            run.accept('accept', 'Check returned value', lambda: True, requires=('read',))
            run.complete()
        self.assertEqual(read_activity(self.root)[0]['agent_id'], 'engineering-manager')
        for index, value in enumerate(['', 'bad role', 'bad\nrole', 1]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.run_task('invalid-agent-'+str(index), agent_id=value)
        self.assertEqual(len(read_activity(self.root)), 1)

    def test_missing_self_and_forward_dependencies_block_callback(self):
        for task, dependencies in [('missing', ('absent',)), ('self', ('blocked',)), ('forward-cycle', ('future',))]:
            calls = []
            with self.assertRaisesRegex(RuntimeError, 'previously checked'):
                with self.run_task(task) as run:
                    run.stage('blocked', 'Blocked', lambda: calls.append(1), requires=dependencies)
            self.assertEqual(calls, [])
            events = read_events(self.root, task)['events']
            self.assertEqual([e['type'] for e in events], ['started', 'failed'])

    def test_unchecked_predecessor_and_failed_check_cannot_satisfy_dependency(self):
        calls = []
        with self.assertRaisesRegex(RuntimeError, 'previously checked'):
            with self.run_task('unchecked') as run:
                run.stage('first', 'Returned without a check', lambda: 1)
                run.stage('second', 'Blocked', lambda: calls.append(1), requires=('first',))
        with self.run_task('failed-check') as run:
            with self.assertRaisesRegex(RuntimeError, 'did not pass'):
                run.stage('first', 'Failed check', lambda: 1, check=lambda result: False)
            with self.assertRaisesRegex(RuntimeError, 'not active'):
                run.stage('second', 'Blocked', lambda: calls.append(2), requires=('first',))
        self.assertEqual(calls, [])

    def test_checked_predecessor_acceptance_and_duplicate_protection(self):
        calls = []
        with self.run_task() as run:
            run.stage('first', 'Checked predecessor', lambda: 7, check=lambda value: value == 7)
            run.stage('second', 'Allowed successor', lambda: calls.append(1),
                      requires=('first',), check=lambda value: value is None)
            with self.assertRaises(AlreadyRecorded):
                run.stage('second', 'Duplicate', lambda: calls.append(2), requires=('first',))
            run.accept('final', 'Check final outcome', lambda: calls == [1], requires=('first', 'second'))
            run.complete()
        self.assertEqual(calls, [1])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime')
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_task(self, task='task', **kwargs):
        return NativeExecution(self.root, task, 'Actual callback task', chat_id='chat:one', **kwargs)

    def test_start_before_callback_order_and_checked_completion(self):
        def callback():
            self.assertEqual([e['type'] for e in read_events(self.root, 'task')['events']], ['started', 'step'])
            self.assertEqual(read_events(self.root, 'task')['events'][-1]['reads'], [])
            return 3
        with self.run_task() as run:
            self.assertEqual(run.stage('read', 'Read source', callback,
                                       reads=[dict(label='Source', reference='C:/source', version='v1')]), 3)
            with self.assertRaisesRegex(RuntimeError, 'acceptance'):
                run.complete('A fluent summary')
            run.accept('check', 'Check callback result', lambda: True)
            run.complete()
        events = read_events(self.root, 'task')['events']
        self.assertEqual([e['type'] for e in events], ['started', 'step', 'step', 'step', 'step', 'completed'])
        self.assertEqual(events[2]['reads'][0]['version'], 'v1')
        self.assertEqual(read_activity(self.root)[0]['status'], 'completed')

    def test_failure_redaction_and_no_read_claim(self):
        def fail():
            raise ValueError('password=secret-value')
        with self.assertRaises(ValueError):
            with self.run_task() as run:
                run.stage('read', 'Read source', fail, reads=[dict(label='Source', reference='C:/source')])
        history = read_events(self.root, 'task')
        self.assertNotIn('secret-value', str(history))
        self.assertTrue(all(not e['reads'] for e in history['events']))
        self.assertEqual(read_activity(self.root)[0]['status'], 'failed')

    def test_context_requires_acceptance_and_false_check_fails(self):
        with self.run_task('unaccepted'):
            pass
        with self.assertRaisesRegex(RuntimeError, 'did not pass'):
            with self.run_task('false-check') as run:
                run.accept('check', 'Check', lambda: 'true')
        self.assertEqual({r['status'] for r in read_activity(self.root)}, {'failed'})

    def test_duplicate_no_reexecution_and_post_check_invalidated(self):
        calls = []
        with self.run_task() as run:
            run.stage('one', 'One', lambda: calls.append(1))
            with self.assertRaises(AlreadyRecorded):
                run.stage('one', 'One', lambda: calls.append(2))
            run.accept('check', 'Check', lambda: True)
            run.stage('two', 'Two', lambda: None)
            with self.assertRaisesRegex(RuntimeError, 'acceptance'):
                run.complete()
        with self.assertRaises(AlreadyRecorded):
            with self.run_task() as run:
                run.stage('one', 'One', lambda: calls.append(3))
        self.assertEqual(calls, [1])

    def test_cli_bounded_read_and_hash_acceptance(self):
        import hashlib
        from unittest.mock import patch
        source = self.root / 'source.txt'
        source.write_bytes(b'checked source')
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        args = ['--root', str(self.root), '--chat-id', 'chat:cli', '--task-id', 'cli',
                '--source', str(source), '--expected-sha256', digest]
        with patch('builtins.print'):
            self.assertEqual(main(args), 0)
            self.assertEqual(main(args), 2)
            args[args.index('cli')] = 'cli-failed'
            args[-1] = '0' * 64
            self.assertEqual(main(args), 2)
        records = {r['task_id']: r for r in read_activity(self.root)}
        self.assertEqual(records['cli']['status'], 'completed')
        self.assertEqual(records['cli-failed']['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
