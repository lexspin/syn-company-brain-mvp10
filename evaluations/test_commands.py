import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
from commands import CommandQueue, CommandWorker, atomic_json


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'runtime')
        self.queue = CommandQueue(self.temp.name)
        self.brain = Mock()
        self.publisher = Mock()
        self.worker = CommandWorker(self.brain, self.queue, self.publisher)
        self.payload = {'kind':'memory', 'id':'decision', 'data':{'name':'Decision'}, 'version':0}
        self.brain.save.return_value = {'id':'decision','version':1}

    def tearDown(self):
        self.worker.stop()
        self.temp.cleanup()

    def test_enqueue_does_not_execute_or_publish(self):
        id = self.queue.enqueue('save', self.payload)
        request = json.loads(self.queue.path('requests', id).read_text())
        self.assertEqual(request['requested_by'], 'local-owner-ui')
        self.assertIn('requested_at', request)
        self.brain.save.assert_not_called(); self.publisher.publish.assert_not_called()
        self.assertFalse((Path(self.temp.name)/'data').exists())

    def test_duplicate_request_is_executed_once(self):
        id = self.queue.enqueue('save', self.payload)
        self.assertEqual(self.queue.enqueue('save', self.payload, id), id)
        self.worker.run_once(); self.worker.run_once()
        self.brain.save.assert_called_once()
        self.assertTrue(self.queue.receipt(id)['ok'])
        self.assertTrue(self.queue.path('requests', id).exists())
        self.assertTrue(self.queue.path('begun', id).exists())

    def test_duplicate_identity_with_different_payload_is_rejected(self):
        id = self.queue.enqueue('save', self.payload)
        with self.assertRaises(ValueError):
            self.queue.enqueue('save', self.payload|{'id':'another'}, id)

    def test_invalid_route_or_traversal_creates_no_request(self):
        for action, payload in [('shell', {'command':'anything'}), ('save', self.payload|{'id':'../outside'}), ('chat', {'session':'../outside','prompt':'hello','agent':'worker'})]:
            with self.assertRaises(ValueError): self.queue.enqueue(action, payload)
        self.assertEqual(list((self.queue.root/'requests').glob('*.json')), [])

    def test_ambiguous_begun_command_is_not_replayed(self):
        id = self.queue.enqueue('save', self.payload)
        atomic_json(self.queue.path('begun', id), {'id':id})
        self.worker.recover(); self.worker.run_once()
        self.brain.save.assert_not_called()
        receipt = self.queue.receipt(id)
        self.assertEqual(receipt['state'], 'interrupted')
        self.assertEqual(receipt['http_status'], 409)

    def test_stable_start_is_safely_recovered(self):
        self.brain.start.return_value = {'id':'a'*32, 'state':'interrupted'}
        payload = {'id':'report', 'key':'stable-key-1234'}
        id = self.queue.enqueue('start', payload)
        self.assertEqual(self.queue.enqueue('start', payload), id)
        atomic_json(self.queue.path('begun', id), {'id':id})
        self.worker.recover(); self.worker.run_once()
        self.brain.start.assert_called_once_with('report', 'stable-key-1234')
        self.assertTrue(self.queue.receipt(id)['ok'])

    def test_failed_publication_does_not_repeat_successful_action(self):
        self.publisher.publish.side_effect = OSError('projection unavailable')
        id = self.queue.enqueue('save', self.payload)
        self.worker.run_once(); self.worker.run_once()
        self.brain.save.assert_called_once()
        self.assertTrue(self.queue.receipt(id)['ok'])
        self.assertTrue((self.queue.root/'publication-error.json').exists())

    def test_failure_is_recorded_and_retained(self):
        self.brain.save.side_effect = ValueError('Expected version changed.')
        id = self.queue.enqueue('save', self.payload)
        self.worker.run_once()
        self.assertEqual(self.queue.receipt(id)['http_status'], 400)
        self.assertIn('version changed', self.queue.receipt(id)['error'])
        self.assertTrue(self.queue.path('requests', id).exists())

    def test_chat_passes_selected_project_to_backend(self):
        self.brain.chat.return_value = {'text':'answer'}
        id = self.queue.enqueue('chat', {'session':'main','prompt':'Draft a report','agent':'coordinator','project_id':'lab'})
        self.worker.run_once()
        self.brain.chat.assert_called_once_with('main','Draft a report','coordinator',project_id='lab')
        self.assertTrue(self.queue.receipt(id)['ok'])

    def test_deterministic_chat_uses_fast_publication(self):
        result={'text':'Saved answer','mode':'l1_lookup','model_calls':0}
        self.brain.chat.return_value=result
        id=self.queue.enqueue('chat',{'session':'main','prompt':'memory:policy','agent':'auto'})
        self.worker.run_once()
        self.publisher.publish_chat.assert_called_once_with('main');self.publisher.publish.assert_not_called()
        self.assertEqual(self.queue.receipt(id)['result'],result)

    def test_fast_publication_failure_falls_back_without_repeating_chat(self):
        result={'text':'Saved answer','mode':'l1_reuse','model_calls':0}
        self.brain.chat.return_value=result
        self.publisher.publish_chat.side_effect=FileNotFoundError('Missing first view')
        id=self.queue.enqueue('chat',{'session':'main','prompt':'Previous question','agent':'auto'})
        self.worker.run_once();self.worker.run_once()
        self.publisher.publish.assert_called_once_with();self.brain.chat.assert_called_once()
        self.assertEqual(self.queue.receipt(id)['result'],result)

    def test_all_publication_failures_preserve_completed_fast_answer_receipt(self):
        self.brain.chat.return_value={'text':'Saved answer','mode':'l1_lookup','model_calls':0}
        self.publisher.publish_chat.side_effect=OSError('Fast view unavailable')
        self.publisher.publish.side_effect=OSError('Full view unavailable')
        id=self.queue.enqueue('chat',{'session':'main','prompt':'memory:policy','agent':'auto'})
        self.worker.run_once()
        self.assertTrue(self.queue.receipt(id)['ok']);self.brain.chat.assert_called_once()
        self.assertTrue((self.queue.root/'publication-error.json').exists())

    def test_timeout_preserves_pending_request(self):
        id = self.queue.enqueue('save', self.payload)
        receipt = self.queue.wait(id, timeout=0)
        self.assertEqual(receipt['state'], 'pending')
        self.assertTrue(self.queue.path('requests', id).exists())

    def test_corrupt_request_is_retained_without_blocking_other_work(self):
        path = self.queue.path('requests', 'b'*32)
        path.write_text('{broken', encoding='utf-8')
        good = self.queue.enqueue('save', self.payload)
        self.worker.run_once()
        self.assertEqual(self.queue.receipt('b'*32)['state'], 'failed')
        self.assertTrue(path.exists())
        self.assertTrue(self.queue.receipt(good)['ok'])
        self.brain.save.assert_called_once()

    def test_saved_request_cannot_choose_another_identity(self):
        id = self.queue.enqueue('save', self.payload)
        path = self.queue.path('requests', id)
        request = json.loads(path.read_text()) | {'id':'c'*32}
        atomic_json(path, request)
        self.worker.run_once()
        self.assertEqual(self.queue.receipt(id)['state'], 'failed')
        self.assertIsNone(self.queue.receipt('c'*32))
        self.brain.save.assert_not_called()

    def test_archive_union_rejects_ambiguous_sources(self):
        with self.assertRaises(ValueError):
            self.queue.enqueue('archive-research', {'turn_id':'c'*32, 'content':'extra'})
        with self.assertRaises(ValueError):
            self.queue.enqueue('archive-research', {'turn_id':'c'*32, 'skill_ids':['../../other']})

    def test_archive_calls_completed_turn_capture(self):
        with patch('archive_research.capture', return_value={'id':'research-test'}) as capture:
            id = self.queue.enqueue('archive-research', {'turn_id':'c'*32, 'project_id':'lab'})
            self.worker.run_once()
            capture.assert_called_once_with(self.brain, 'c'*32, project_id='lab', skill_ids=None)
        self.assertTrue(self.queue.receipt(id)['ok'])


if __name__ == '__main__': unittest.main()
