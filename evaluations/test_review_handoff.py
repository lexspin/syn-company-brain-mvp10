"""Real isolated archive/queue effects; no production requests or model calls."""
import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
from brain import Brain
from commands import CommandQueue, CommandWorker
from read_models import Publisher
from review_handoff import preparation, queue_handoff, fingerprint, _archive_module


class ReviewHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'runtime')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.brain = Brain(self.root)
        self.brain.save('skill', 'reviewer', {'name': 'Reviewer', 'instructions': 'Review exact inputs.'})
        self.brain.save('project', 'work', {'name': 'Work', 'path': str(self.root), 'scope': 'Fixture', 'refs': []})
        self.brain.save('loop', 'connected-change-review', {'name': 'Connected review', 'instructions': 'Check source impact.', 'steps': [], 'refs': ['skill:reviewer'], 'execution': {'type': 'codex-chat', 'trigger': 'work-outcome', 'skill_id': 'reviewer'}})
        self.brain.save('stack', 'operating-policy', {'name': 'Policy', 'schema_version': 1, 'requested_state': 'active'})
        self.q = CommandQueue(self.root)
        self.publisher = Publisher(self.brain)
        self.worker = CommandWorker(self.brain, self.q, self.publisher)
        self.no_changes = patch.object(self.worker, '_changes', return_value=None, create=True)
        self.no_changes.start(); self.addCleanup(self.no_changes.stop)
        self.content = 'Original checked result.\nPreserve exact wording — no rewrite.'
        payload = {'title': 'Actual fixture archive', 'content': self.content, 'project_id': 'work', 'skill_ids': ['reviewer'], 'request_key': 'fixture-archive-handoff', 'provenance': {'chat_id': 'actual-fixture-chat'}}
        rid = self.q.enqueue('archive-research', payload); self.worker.run_once()
        self.receipt = self.q.receipt(rid)
        self.assertTrue(self.receipt['ok'], self.receipt)
        self.source = self.receipt['result']
        self.bindings = {'source_id': self.source['id'], 'source_version': self.source['version'], 'content_sha256': fingerprint(self.content), 'archive_receipt': rid, 'source_chat': 'actual-fixture-chat', 'project_id': 'work', 'scope': 'Review future research alignment, procedure quality and useful failure lessons only.', 'root': self.root}
        fixture = self
        self.bindings['impact_kind'] = 'workflow-change'
        class Reader:
            def state(self):
                value = json.loads((fixture.root/'data/state.json').read_text(encoding='utf-8'))
                if 'data' in value: value = value['data']
                value['_view'] = {'asof': datetime.now(timezone.utc).isoformat(), 'stale': False}
                return value
            def receipt(self, identity): return fixture.q.receipt(identity)
        self.reader = Reader()
        self.module = _archive_module()
        self.calls = []
        class Writer:
            def receipt(self, identity):
                try:
                    result = fixture.q.receipt(identity)
                    if result is None: raise ValueError('missing')
                    return result
                except (ValueError, FileNotFoundError): raise HTTPError('local', 404, 'missing', {}, None)
            def command(self, action, payload):
                fixture.calls.append(copy.deepcopy(payload))
                identity = fixture.module.stable_id(action, payload)
                fixture.q.enqueue(action, payload, request_id=identity)
                fixture.worker.run_once()
                return fixture.q.receipt(identity)
        self.writer = Writer()

    def prepare(self, **changes): return preparation(self.reader, **(self.bindings | changes))

    def test_prepare_is_read_only_exact_context_and_source_preserved(self):
        before = self.brain.get('memory', self.source['id'])
        requests = set((self.root/'runtime/queue/requests').glob('*.json'))
        prepared = self.prepare()
        self.assertEqual(requests, set((self.root/'runtime/queue/requests').glob('*.json')))
        self.assertEqual(self.brain.get('memory', self.source['id']), before)
        data = prepared['save_payload']['data']; context = json.loads(data['request_input'])
        self.assertEqual(context['scope'], self.bindings['scope'])
        self.assertEqual(context['source_chat'], 'actual-fixture-chat')
        self.assertEqual(context['source_version'], before['version'])
        self.assertEqual(context['content_sha256'], fingerprint(self.content))
        self.assertNotIn(self.content, data['request_input'])
        self.assertEqual(data['request_state'], 'queued')
        self.assertNotIn('completion_check', data)
        self.assertEqual(prepared['save_payload']['version'], 0)
        self.assertIn('memory:'+before['id'], data['refs'])

    def test_actual_queue_deduplicates_and_does_not_complete_original_work(self):
        first = queue_handoff(self.reader, self.writer, **self.bindings)
        self.assertEqual(first['queue_receipt']['state'], 'completed')
        result = self.brain.get('memory', first['request_id'])
        self.assertEqual(result['data']['request_state'], 'queued')
        second = queue_handoff(self.reader, self.writer, **self.bindings)
        self.assertEqual(second['request_id'], first['request_id'])
        self.assertEqual(second['existing']['state'], 'queued')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.brain.get('memory', self.source['id'])['data']['content'], self.content)

    def test_wrong_version_hash_missing_archived_and_stale_source_rejected(self):
        for changes in ({'source_version': 99}, {'content_sha256': 'a'*64}, {'source_id': 'missing'}, {'source_version': True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.prepare(**changes)
        original = self.reader.state
        for mutation in ('archived', 'candidate', 'stale'):
            state = original()
            source = next(r for r in state['objects'] if r['kind'] == 'memory' and r['id'] == self.source['id'])
            if mutation == 'archived': source['archived'] = True
            elif mutation == 'candidate': source['data']['status'] = 'candidate'
            else: state['memory_freshness'][self.source['id']]['current'] = False
            with patch.object(self.reader, 'state', return_value=state), self.assertRaises(ValueError): self.prepare()

    def test_wrong_receipt_chat_project_and_unavailable_receipt_rejected(self):
        for changes in ({'archive_receipt': 'f'*32}, {'source_chat': 'other-chat'}, {'project_id': 'missing'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.prepare(**changes)
        altered = copy.deepcopy(self.receipt); altered['action'] = 'save'
        with patch.object(self.reader, 'receipt', return_value=altered), self.assertRaises(ValueError): self.prepare()

    def test_reviewer_output_explicit_provenance_skips_self_churn(self):
        state = self.reader.state()
        source = next(r for r in state['objects'] if r['kind'] == 'memory' and r['id'] == self.source['id'])
        source['data']['refs'].append('loop:connected-change-review')
        with patch.object(self.reader, 'state', return_value=state), self.assertRaisesRegex(ValueError, 'self-churn'):
            self.prepare()
        self.assertEqual(self.calls, [])

    def test_pure_checks_and_unknown_impact_do_not_prepare_or_queue(self):
        for value in ('pure-check', '', None, 'speculation'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'pure checks'):
                self.prepare(impact_kind=value)
        self.assertEqual(self.calls, [])

    def test_running_predecessor_survives_scope_and_workflow_version_change(self):
        prepared = self.prepare(); state = self.reader.state()
        data = prepared['save_payload']['data'] | {'request_state': 'running', 'claimant': 'other-owner', 'claimed_at': 'actual'}
        state['objects'].append({'kind': 'memory', 'id': prepared['request_id'], 'version': 2, 'archived': False, 'data': data})
        next(r for r in state['objects'] if r['kind'] == 'loop')['version'] += 1
        with patch.object(self.reader, 'state', return_value=state):
            result = queue_handoff(self.reader, self.writer, **(self.bindings | {'scope': 'Changed review scope'}))
        self.assertEqual(result['request_id'], prepared['request_id'])
        self.assertEqual(result['existing']['state'], 'running')
        self.assertEqual(result['context']['scope'], self.bindings['scope'])
        self.assertEqual(self.calls, [])

    def test_publication_root_stale_and_policy_off_fail_without_write(self):
        original = self.reader.state
        for mutation in ('root', 'stale', 'off', 'missing-policy'):
            state = original()
            if mutation == 'root': state['root'] = str(self.root/'wrong')
            elif mutation == 'stale': state['_view']['asof'] = (datetime.now(timezone.utc)-timedelta(seconds=60)).isoformat()
            elif mutation == 'off': next(r for r in state['objects'] if r['id'] == 'operating-policy')['data']['requested_state'] = 'off'
            else: state['objects'] = [r for r in state['objects'] if r['id'] != 'operating-policy']
            with self.subTest(mutation=mutation), patch.object(self.reader, 'state', return_value=state), self.assertRaises(ValueError): queue_handoff(self.reader, self.writer, **self.bindings)
        self.assertEqual(self.calls, [])

    def test_idle_allows_review_preparation_as_routine_but_not_execution_claim(self):
        state = self.reader.state()
        next(r for r in state['objects'] if r['id'] == 'operating-policy')['data']['requested_state'] = 'idle'
        with patch.object(self.reader, 'state', return_value=state): self.assertIn('save_payload', self.prepare())

    def test_pending_uncertain_original_command_is_never_resubmitted(self):
        prepared = self.prepare(); identity = self.module.stable_id('save', prepared['save_payload'])
        with patch.object(self.writer, 'receipt', return_value={'id': identity, 'action': 'save', 'state': 'uncertain', 'ok': False}):
            result = queue_handoff(self.reader, self.writer, **self.bindings)
        self.assertEqual(result['queue_receipt']['state'], 'uncertain')
        self.assertEqual(self.calls, [])

    def test_conflicting_existing_request_and_changed_before_send_rejected(self):
        prepared = self.prepare()
        state = self.reader.state()
        data = prepared['save_payload']['data'] | {'request_input': 'Changed context'}
        state['objects'].append({'kind': 'memory', 'id': prepared['request_id'], 'version': 1, 'archived': False, 'data': data})
        with patch.object(self.reader, 'state', return_value=state), self.assertRaises(ValueError): self.prepare()
        original = self.reader.state; state = original()
        next(r for r in state['objects'] if r['kind'] == 'loop')['version'] += 1
        with patch.object(self.reader, 'state', side_effect=[original(), state]), self.assertRaises(ValueError):
            queue_handoff(self.reader, self.writer, **self.bindings)
        self.assertEqual(self.calls, [])


if __name__ == '__main__': unittest.main()
