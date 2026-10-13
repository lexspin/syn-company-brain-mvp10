import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from task_trace import verify

class TraceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.output=Path(self.tmp.name)/'output.txt';self.output.write_text('Checked fixture output')
        digest=hashlib.sha256(self.output.read_bytes()).hexdigest()
        self.plan={'trace_id':'trial','steps':[]};self.events=[]
        for i,role in enumerate(['executive','manager','specialist','reviewer','archive']):
            key=str(i);self.plan['steps'].append({'id':key,'owner':role,'source_version':'fixture@1','acceptance':'Exact output is retained','depends_on':[str(i-1)] if i else []})
            base={'trace_id':'trial','step_id':key,'operation_id':'op-'+key}
            self.events += [base|{'kind':'request','source_version':'fixture@1'},base|{'kind':'response','status':'returned','artifact':{'path':str(self.output),'sha256':digest}},base|{'kind':'validation','status':'passed','artifact_sha256':digest,'evidence':'Fixture exact-output assertion'}]
    def test_full_chain(self):self.assertEqual(verify(self.plan,self.events)['status'],'verified')
    def test_missing_response(self):
        del self.events[7];self.assertEqual(verify(self.plan,self.events)['status'],'needs-review')
    def test_wrong_correlation(self):
        self.events[7]['operation_id']='other';self.assertEqual(verify(self.plan,self.events)['status'],'needs-review')
    def test_stale_source(self):
        self.events[0]['source_version']='fixture@0';self.assertEqual(verify(self.plan,self.events)['status'],'needs-review')
    def test_failed_leaf_cannot_be_hidden(self):
        self.events[8]['status']='failed';self.assertEqual(verify(self.plan,self.events)['steps'][-1]['status'],'unverified')
    def test_early_handoff(self):
        self.events=self.events[3:6]+self.events[:3]+self.events[6:];self.assertEqual(verify(self.plan,self.events)['status'],'needs-review')
    def test_duplicate_effect_receipt(self):
        self.events.insert(1,copy.deepcopy(self.events[0]));self.assertEqual(verify(self.plan,self.events)['status'],'needs-review')
    def test_modified_output(self):
        self.output.write_text('changed');self.assertEqual(verify(self.plan,self.events)['status'],'needs-review')
    def test_foreign_event(self):
        self.events.append({'trace_id':'other'});self.assertEqual(verify(self.plan,self.events)['status'],'needs-review')
    def test_cycle(self):
        self.plan['steps'][0]['depends_on']=['4']
        with self.assertRaises(ValueError):verify(self.plan,self.events)
    def test_plan_order_does_not_change_dependency_order(self):
        self.plan['steps'].reverse();self.assertEqual(verify(self.plan,self.events)['status'],'verified')
    def test_cross_task_operation_reuse(self):
        for e in self.events[3:6]:e['operation_id']='op-0'
        self.assertEqual(verify(self.plan,self.events)['status'],'needs-review')

if __name__=='__main__':unittest.main()
