import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
from lifecycle import cleanup, digest, now, recall, scratch_lease

class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'runtime')
        self.root = Path(self.temp.name)
        for folder in ('runtime/scratch/check', 'deliverables/final', 'data'):
            (self.root/folder).mkdir(parents=True)
        self.scratch = self.root/'runtime/scratch/check/test.txt'; self.scratch.write_text('discarded test')
        self.target = self.root/'deliverables/final/result.txt'; self.target.write_text('validated final')
        self.binding = {'path': 'deliverables/final/result.txt', 'sha256': digest(self.target)}
        self.proof = self.root/'deliverables/final/validation.json'
        self.proof.write_text(json.dumps({'status':'passed', 'artifact':self.binding, 'method':'Reloaded UTF-8 output and compared expected text', 'checked_at':now()}))
        self.manifest = {'work_id':'check', 'completed':True, 'files':[{'path':'runtime/scratch/check/test.txt', 'sha256':digest(self.scratch), 'kind':'test-output', 'reason':'Replaced by checked final output', 'replacement':self.binding, 'validation':{'path':'deliverables/final/validation.json', 'sha256':digest(self.proof)}}]}
        self.state = {'objects':[], 'runs':[], 'worker_busy':False, 'memory_freshness':{}, '_view':{'asof':now(), 'stale_after_seconds':30}}
        self.publish()
    def tearDown(self): self.temp.cleanup()
    def publish(self): (self.root/'data/state.json').write_text(json.dumps(self.state))
    def test_dry_run_changes_no_files_and_apply_preserves_replacement_and_logs_deletion(self):
        before = set(self.root.rglob('*')); result = cleanup(self.root, self.manifest)
        self.assertTrue(result['dry_run']); self.assertEqual(before,set(self.root.rglob('*'))); self.assertTrue(self.scratch.exists())
        result = cleanup(self.root, self.manifest, apply=True)
        self.assertTrue(result['changed']); self.assertFalse(self.scratch.exists()); self.assertEqual(self.target.read_text(),'validated final')
        events=[json.loads(line) for line in (self.root/'store/lifecycle/events.jsonl').read_text().splitlines()]
        self.assertEqual([e['event'] for e in events],['delete-started','deleted']); self.assertEqual(events[-1]['retained_replacement'],self.binding)
        self.assertFalse(cleanup(self.root,self.manifest,apply=True)['changed'])
    def test_changed_scratch_or_replacement_is_retained(self):
        self.scratch.write_text('new unique work')
        with self.assertRaisesRegex(ValueError,'changed'):cleanup(self.root,self.manifest,True)
        self.assertTrue(self.scratch.exists());self.assertFalse((self.root/'store/lifecycle').exists())
        self.scratch.write_text('discarded test');self.target.write_text('unchecked next version')
        with self.assertRaisesRegex(ValueError,'replacement'):cleanup(self.root,self.manifest,True)
        self.assertTrue(self.scratch.exists())
    def test_only_owned_scratch_is_eligible_and_path_traversal_rejected(self):
        self.manifest['files'][0]['path']='deliverables/final/result.txt'
        with self.assertRaisesRegex(ValueError,'runtime/scratch'):cleanup(self.root,self.manifest)
        self.manifest['files'][0]['path']='runtime/scratch/check/../../../deliverables/final/result.txt'
        with self.assertRaisesRegex(ValueError,'traversal'):cleanup(self.root,self.manifest)
        self.assertTrue(self.target.exists())
    def test_unvalidated_replacement_and_busy_or_stale_workspace_prevent_cleanup(self):
        proof=json.loads(self.proof.read_text());proof['status']='not-checked';self.proof.write_text(json.dumps(proof));self.manifest['files'][0]['validation']['sha256']=digest(self.proof)
        with self.assertRaisesRegex(ValueError,'passed'):cleanup(self.root,self.manifest,True)
        proof['status']='passed';self.proof.write_text(json.dumps(proof));self.manifest['files'][0]['validation']['sha256']=digest(self.proof)
        self.state['worker_busy']=True;self.publish()
        with self.assertRaisesRegex(ValueError,'active'):cleanup(self.root,self.manifest,True)
        self.state['worker_busy']=False;self.state['_view']['asof']='2020-01-01T00:00:00+00:00';self.publish()
        with self.assertRaisesRegex(ValueError,'fresh'):cleanup(self.root,self.manifest,True)
        self.assertTrue(self.scratch.exists())
    def test_pending_command_and_owned_scratch_lease_prevent_cleanup(self):
        request=self.root/'runtime/queue/requests/id.json';request.parent.mkdir(parents=True);request.write_text('{}')
        with self.assertRaisesRegex(ValueError,'commands'):cleanup(self.root,self.manifest,True)
        request.unlink()
        with scratch_lease(self.root,'check'):
            with self.assertRaisesRegex(ValueError,'leased'):cleanup(self.root,self.manifest,True)
        self.assertTrue(self.scratch.exists())
    def test_recall_prefers_selected_project_memory_and_excludes_stale_sources(self):
        def record(kind,id,**data):return {'kind':kind,'id':id,'archived':False,'version':2,'data':{'name':id,**data}}
        self.state['objects']=[record('project','one',path=str(self.root),scope='A scoped product',refs=['memory:linked','memory:old']),record('memory','linked',content='Current outcome evidence',source='owner'),record('memory','old',content='outcome stale fact',source='old'),record('memory','query',content='outcome query evidence',source='source')]
        self.state['memory_freshness']={'linked':{'current':True},'old':{'current':False},'query':{'current':True}};self.publish()
        before=set(self.root.rglob('*'));result=recall(self.root,'outcome',project_id='one')
        self.assertEqual([r['id'] for r in result['memory']],['linked','query']);self.assertEqual(result['memory'][0]['citation'],'[linked@2]')
        self.assertEqual(result['project']['scope'],'A scoped product');self.assertEqual(before,set(self.root.rglob('*')))
        with self.assertRaisesRegex(ValueError,'not active'):recall(self.root,'outcome',project_id='missing')
    def test_large_project_library_does_not_crowd_out_query_relevant_source(self):
        rows=[{'kind':'memory','id':'unrelated-'+str(i),'archived':False,'version':1,'data':{'name':'Blender material','content':'Shader colors and lighting','source':'journal'}} for i in range(12)]
        relevant={'kind':'memory','id':'hades-dialogue','archived':False,'version':1,'data':{'name':'Hades dialogue','content':'Relevant game conversation research','source':'talk'}}
        self.state['objects']=[{'kind':'project','id':'company','archived':False,'version':1,'data':{'name':'Company','path':str(self.root),'scope':'shared library','refs':['memory:'+r['id'] for r in rows]}}]+rows+[relevant]
        self.state['memory_freshness']={r['id']:{'current':True} for r in rows+[relevant]};self.publish()
        result=recall(self.root,'Hades dialogue',project_id='company')
        self.assertEqual([r['id'] for r in result['memory']],['hades-dialogue'])

if __name__=='__main__': unittest.main()
