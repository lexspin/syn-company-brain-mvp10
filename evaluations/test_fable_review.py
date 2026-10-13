import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from fable_review import Claim, Observation, review_claims


class ClaimReviewTests(unittest.TestCase):
    def test_actual_file_and_receipt_observations(self):
        with tempfile.TemporaryDirectory() as folder:
            artifact = Path(folder) / 'artifact.txt'
            artifact.write_text('accepted output', encoding='utf-8')
            receipt = Path(folder) / 'receipt.json'
            receipt.write_text(json.dumps({'status': 'saved', 'version': 2}))
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            before = artifact.read_bytes(), receipt.read_bytes()
            result = review_claims([Claim('artifact', 'Artifact matches accepted bytes', digest),
                                   Claim('receipt', 'Receipt saved version', 'saved:2')], {
                'artifact': lambda: Observation(hashlib.sha256(artifact.read_bytes()).hexdigest(), (str(artifact),)),
                'receipt': lambda: Observation(':'.join(str(json.loads(receipt.read_text())[k]) for k in ('status', 'version')), (str(receipt),))})
            self.assertFalse(result['review_required'])
            self.assertEqual([row['status'] for row in result['claims']], ['observed-match'] * 2)
            self.assertEqual(before, (artifact.read_bytes(), receipt.read_bytes()))

    def test_contradiction_missing_exception_and_exactly_once(self):
        calls = []

        def observed():
            calls.append('observed')
            return Observation('4', ('fixture:observed-row-count',))

        def broken():
            calls.append('broken')
            raise RuntimeError('PRIVATE raw path or request')

        result = review_claims([Claim('count', 'All five rows retained', '5'),
                               Claim('missing', 'Unobserved screenshot', 'matches'),
                               Claim('error', 'Unavailable check', 'ready')],
                              {'count': observed, 'error': broken})
        self.assertEqual(calls, ['observed', 'broken'])
        self.assertEqual([row['status'] for row in result['claims']], ['refuted', 'unverified', 'check-error'])
        self.assertTrue(result['review_required'])
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_duplicate_and_capacity_rejected_before_callbacks(self):
        calls = []
        claim = Claim('one', 'One claim', 'yes')
        observer = lambda: calls.append('called')
        for claims in ([claim, claim], [Claim('id-' + str(i), 'Claim', 'yes') for i in range(33)]):
            with self.assertRaises(ValueError):
                review_claims(claims, {'one': observer})
        self.assertEqual(calls, [])
        result = review_claims([Claim('id-' + str(i), 'Claim', 'yes') for i in range(32)], {})
        self.assertEqual(len(result['claims']), 32)
        self.assertTrue(result['review_required'])

    def test_bare_true_or_missing_evidence_is_not_observation(self):
        for returned in (True, Observation('yes', ())):
            result = review_claims([Claim('claim', 'Claim', 'yes')], {'claim': lambda: returned})
            self.assertEqual(result['claims'][0]['status'], 'check-error')
            self.assertTrue(result['review_required'])

    def test_callbacks_cannot_mutate_validated_scope_or_observer_bindings(self):
        calls = []
        claims = [Claim('first', 'First', 'ok'), Claim('second', 'Second', 'ok'),
                  Claim('missing', 'Must remain unverified', 'ok')]
        observers = {}

        def mutate():
            claims.clear()
            claims.extend(Claim('extra-' + str(i), 'Injected', 'ok') for i in range(40))
            observers['second'] = lambda: calls.append('replacement')
            observers['missing'] = lambda: Observation('ok', ('fixture:injected',))
            return Observation('ok', ('fixture:first',))

        def second():
            calls.append('original')
            return Observation('ok', ('fixture:second',))

        observers.update(first=mutate, second=second)
        result = review_claims(claims, observers)
        self.assertEqual(calls, ['original'])
        self.assertEqual([row['id'] for row in result['claims']], ['first', 'second', 'missing'])
        self.assertEqual(result['claims'][-1]['status'], 'unverified')
        self.assertTrue(result['review_required'])


if __name__ == '__main__':
    unittest.main()
