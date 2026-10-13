"""Adversarial fixtures: generated text is deliberately hostile, never live memory."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import unittest
import test_brain
import test_commands


class AdversarialBrain(unittest.TestCase):
    def setUp(self):
        self.fixture = test_brain.BrainTests(); self.fixture.setUp(); self.b = self.fixture.b

    def tearDown(self): self.fixture.tearDown()

    def run_text(self, text):
        r = self.fixture.start_without_thread()
        with patch('codex_runtime.run', return_value={'text': text}): self.b.execute(r['id'])
        return self.b.run(r['id'])

    def test_invented_source_fails(self):
        self.assertEqual(self.run_text('Use pounds [policy@1]. Approved [invented@1].')['state'], 'failed')

    def test_stale_source_version_fails(self):
        self.assertEqual(self.run_text('Use pounds [policy@999].')['state'], 'failed')

    def test_false_claim_with_real_citation_is_not_automatically_accepted(self):
        r = self.run_text('The owner requires dollars, not pounds [policy@1].')
        # Mechanical validation cannot prove entailment; preserve this gap explicitly.
        self.assertEqual(r['state'], 'needs_review')
        with self.assertRaises(ValueError): self.b.retain(r['id'])
        self.assertEqual(self.b.get('memory','policy')['data']['content'], 'Use whole pounds.')

    def test_twenty_competing_corrections_preserve_one_winner(self):
        def change(n):
            try:
                self.b.save('memory','policy',self.b.get('memory','policy')['data']|{'content':str(n)},1)
                return True
            except ValueError: return False
        with ThreadPoolExecutor(max_workers=8) as pool: results = list(pool.map(change,range(20)))
        self.assertEqual(sum(results),1)
        self.assertEqual(self.b.get('memory','policy')['version'],2)


class AdversarialQueue(unittest.TestCase):
    def test_one_hundred_duplicate_submissions_execute_once(self):
        f = test_commands.CommandTests(); f.setUp()
        try:
            key='a'*32
            with ThreadPoolExecutor(max_workers=12) as pool:
                ids=list(pool.map(lambda _: f.queue.enqueue('save',f.payload,key),range(100)))
            self.assertEqual(set(ids),{key})
            for _ in range(5): f.worker.run_once()
            self.assertEqual(f.brain.save.call_count,1)
            self.assertTrue(f.queue.receipt(key)['ok'])
        finally: f.tearDown()
