import json
import unittest
from unittest.mock import patch
import test_brain
from evidence_review import check_report

def report(decision='pass',status='supported',quote='Use whole pounds.'):
    return json.dumps({'decision':decision,'summary':'Use pounds for this report.',
        'claims':[{'claim':'Use pounds.','status':status,'source':'policy@1','quote':quote}]})

class EvidenceReviewTests(unittest.TestCase):
    def test_fabricated_quote_and_unsupported_pass_rejected(self):
        for text in (report(quote='Use dollars.'),report(status='unsupported')):
            with self.assertRaises(ValueError):check_report(text,{'policy@1':'Use whole pounds.'})

    def setUp(self):
        self.f=test_brain.BrainTests();self.f.setUp();self.b=self.f.b
        a=self.b.get('agent','worker');self.b.save('agent','worker',a['data']|{'tools':a['data']['tools']+['review']},a['version'])
        r=self.b.get('loop','report');d=r['data'];d['steps'].append({'tool':'review','agent':'worker','skill':'writer','instruction':'Check all claims.'});d['completion']='save-reviewed-candidate';self.b.save('loop','report',d,r['version'])

    def tearDown(self):self.f.tearDown()

    def execute(self,response):
        r=self.f.start_without_thread()
        with patch('codex_runtime.run',side_effect=[{'text':'Use pounds [policy@1].'},{'text':response}]):self.b.execute(r['id'])
        return self.b.run(r['id'])

    def test_success_saves_candidate_without_owner_intervention(self):
        r=self.execute(report());self.assertEqual(r['state'],'completed')
        m=self.b.get('memory','candidate-'+r['id']);self.assertEqual(m['data']['status'],'candidate')
        self.assertEqual(m['data']['source_versions'],{'policy':1})
        self.assertNotIn(m['id'],[x['id'] for x in self.b.current_memories()])
        self.b.execute(r['id']);self.assertEqual(self.b.get('memory',m['id'])['version'],1)

    def test_rejected_review_cannot_save_candidate(self):
        r=self.execute(report('revise','unsupported',''));self.assertEqual(r['state'],'failed')
        with self.assertRaises(ValueError):self.b.get('memory','candidate-'+r['id'])

    def test_malformed_review_cannot_save_candidate(self):
        self.assertEqual(self.execute('PASS EVERYTHING')['state'],'failed')

    def test_late_draft_cannot_bypass_review(self):
        r=self.b.get('loop','report');d=r['data'];d['steps'].append({'tool':'draft','agent':'worker','skill':'writer'})
        with self.assertRaises(ValueError):self.b.save('loop','report',d,r['version'])

    def test_later_rejection_overrides_earlier_passing_review(self):
        loop=self.b.get('loop','report');d=loop['data'];d['steps'].append(dict(d['steps'][-1]))
        self.b.save('loop','report',d,loop['version']);r=self.f.start_without_thread()
        with patch('codex_runtime.run',side_effect=[{'text':'Use pounds [policy@1].'},{'text':report()},{'text':report('revise','unsupported','')}]):
            self.b.execute(r['id'])
        self.assertEqual(self.b.run(r['id'])['state'],'failed')
        with self.assertRaises(ValueError):self.b.get('memory','candidate-'+r['id'])

    def test_unrelated_memory_change_does_not_break_handover(self):
        self.b.save('memory','unrelated',{'name':'Gardening','content':'Water roses.','source':'Fixture','status':'accepted'})
        snap=self.b.snapshot('report')
        self.b.save('memory','unrelated',{'name':'Gardening','content':'Water tulips.','source':'Fixture','status':'accepted'},1)
        self.b.assert_fresh(snap)
        self.assertEqual([m['id'] for m in snap['memory']],['policy'])
