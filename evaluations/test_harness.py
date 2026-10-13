import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('harness_check',Path(__file__).resolve().parents[1]/'skills/company-brain-harness/scripts/check.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);p=Path(self.tmp.name)
        s=p/'source.txt';s.write_text('source');a=p/'result.txt';a.write_text('actual result')
        self.c={'outcome':'checked result','request_source':'chat:test','project_root':str(p),'skills':['test@1'],'tools':[], 'attempt':1,'max_attempts':2,'elapsed_seconds':1,'timeout_seconds':60,'uncertain_effect':False,'sources':[{'path':str(s),'sha256':m.digest(s)}],'artifacts':[{'path':str(a),'sha256':m.digest(a)}],'requirements':[{'id':'one','description':'Expected result checked','depends_on':[],'status':'passed','evidence':[0]}]}
    def test_actual_file_and_checks_pass(self):self.assertEqual(m.evaluate(self.c)['action'],'complete')
    def test_changed_source_replans(self):
        Path(self.c['sources'][0]['path']).write_text('changed');self.assertEqual(m.evaluate(self.c)['action'],'replan')
    def test_fabricated_pass_without_evidence_reviews(self):
        self.c['requirements'][0]['evidence']=[];self.assertEqual(m.evaluate(self.c)['action'],'review')
    def test_changed_output_reviews(self):
        Path(self.c['artifacts'][0]['path']).write_text('changed');self.assertEqual(m.evaluate(self.c)['action'],'review')
    def test_uncertain_effect_never_replays(self):
        self.c['uncertain_effect']=True;self.c['elapsed_seconds']=999;self.assertEqual(m.evaluate(self.c)['action'],'reconcile')
    def test_exhausted_failed_task_stops(self):
        self.c['requirements'][0]['status']='failed';self.c['attempt']=2;self.assertEqual(m.evaluate(self.c)['action'],'stop')
    def test_cycles_and_missing_dependencies_rejected(self):
        for dep in ('one','missing'):
            self.c['requirements'][0]['depends_on']=[dep]
            with self.assertRaises(ValueError):m.evaluate(self.c)
    def test_unknown_prerequisite_not_complete(self):
        self.c['requirements'][0]['status']='unknown';self.c['requirements'].append({'id':'two','description':'next','depends_on':['one'],'status':'passed','evidence':[0]});self.assertEqual(m.evaluate(self.c)['action'],'review')
    def test_bool_counter_rejected(self):
        self.c['attempt']=True
        with self.assertRaises(ValueError):m.evaluate(self.c)

if __name__=='__main__':unittest.main()
