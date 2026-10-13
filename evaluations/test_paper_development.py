"""Isolated queue contract checks; no paper, provider call or production write."""
import copy
import hashlib
import json
import importlib.util
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

HELPER=Path(__file__).resolve().parents[1]/'skills/company-brain-living-papers/scripts/impact_plan.py'
spec=importlib.util.spec_from_file_location('paper_impact',HELPER)
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)

class PaperDevelopmentTests(unittest.TestCase):
    def test_actual_backend_archive_module_preload_does_not_shadow_client(self):
        backend_path=Path(__file__).resolve().parents[1]/'app/archive_research.py'
        backend_spec=importlib.util.spec_from_file_location('archive_research',backend_path)
        backend=importlib.util.module_from_spec(backend_spec)
        with patch.object(sys,'path',[str(backend_path.parent),*sys.path]):
            backend_spec.loader.exec_module(backend)
        self.assertFalse(hasattr(backend,'Client'))
        with patch.dict('sys.modules',{'archive_research':backend}):
            loaded_spec=importlib.util.spec_from_file_location('paper_collision_check',HELPER)
            loaded=importlib.util.module_from_spec(loaded_spec);loaded_spec.loader.exec_module(loaded)
            self.assertTrue(callable(loaded.Client))
            self.assertEqual(loaded.Client.__module__,'living_papers_archive_client')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        base=Path(self.temp.name);self.os=base/'os'/'V2';self.paper=base/'papers';self.paper.mkdir()
        def row(kind,ident,data,version=1):return dict(kind=kind,id=ident,version=version,data=data,archived=False)
        self.source=row('memory','result',dict(status='accepted',content='Checked source',refs=[]))
        evidence=base/'checked.md';evidence.write_text('Checked result')
        self.outcome=row('memory','done',dict(type='native-work-request',request_state='completed',
            result_ref='result',completion_check={'schema_version':1,'result_receipt':'b'*32,
                'result_id':'result','result_version':1,
                'result_sha256':hashlib.sha256(json.dumps(self.source['data'],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest(),
                'artifacts':[{'path':str(evidence),'sha256':hashlib.sha256(evidence.read_bytes()).hexdigest()}]}))
        self.state={'objects':[self.source,self.outcome,
            row('project','company-brain-papers',{'path':str(self.paper)}),
            row('loop','living-papers',{'execution':{'type':'codex-chat'}}),
            row('stack','operating-policy',{'schema_version':1,'requested_state':'active'}),
            *[row('skill',ident,{}) for ident in ('company-brain-living-papers','company-brain-writing','company-brain-harness')]],
            'memory_freshness':{'result':{'current':True}}}
        test=self
        class Client:
            root=test.os
            calls=[]
            def receipt(self,ident):return dict(ok=True,state='completed',result=copy.deepcopy(test.outcome if ident=='a'*32 else test.source))
            def command(self,action,payload):
                self.calls.append(payload)
                test.state['objects'].append(row('memory',payload['id'],payload['data']))
                return dict(id='c'*32,state='completed')
        self.client=Client();self.client.calls=[]
        self.args=dict(scope='Annex on checked mechanism',project_id='company-brain-papers',family='company-brain-technical',
            target='draft.md',audience='Technical reviewers',acceptance='Check citations and reopen artifact',
            source_result='result',source_version=1,outcome_receipt='a'*32)

    def test_queue_dedup_and_no_paper_created(self):
        first=helper.development(self.client,self.state,**self.args,queue=True)
        second=helper.development(self.client,self.state,**self.args,queue=True)
        self.assertEqual(first['request_id'],second['existing_request']['id'])
        self.assertEqual(len(self.client.calls),1)
        self.assertFalse(first['paper_created']);self.assertFalse((self.paper/'draft.md').exists())
        self.assertEqual(first['bindings']['review_roles']['manager'],'dependencies and integration acceptance')

    def test_stale_archived_candidate_or_wrong_source_version_rejected(self):
        for field,value in [('archived',True),('version',2)]:
            previous=self.source[field];self.source[field]=value
            with self.assertRaises(ValueError):helper.development(self.client,self.state,**self.args)
            self.source[field]=previous
        self.source['data']['status']='candidate'
        with self.assertRaises(ValueError):helper.development(self.client,self.state,**self.args)
        self.source['data']['status']='accepted';self.state['memory_freshness']['result']['current']=False
        with self.assertRaises(ValueError):helper.development(self.client,self.state,**self.args)

    def test_wrong_family_escape_or_os_root_rejected(self):
        for extra in (dict(family='consent'),dict(target='../escaped.md')):
            with self.assertRaises(ValueError):helper.development(self.client,self.state,**(self.args|extra))
        project=next(r for r in self.state['objects'] if r['kind']=='project')
        self.os.mkdir(parents=True);project['data']['path']=str(self.os)
        with self.assertRaises(ValueError):helper.development(self.client,self.state,**self.args)

    def test_unchecked_outcome_rejected_and_off_blocks_queue(self):
        self.outcome['data']['completion_check']={}
        with self.assertRaises(ValueError):helper.development(self.client,self.state,**self.args,queue=True)
        policy=next(r for r in self.state['objects'] if r['kind']=='stack')
        policy['data']['requested_state']='off'
        with self.assertRaisesRegex(ValueError,'blocks'):helper.development(self.client,self.state,**self.args,queue=True)
        self.assertEqual(self.client.calls,[])

    def test_idle_may_queue_scoped_work_but_does_not_execute(self):
        policy=next(r for r in self.state['objects'] if r['kind']=='stack')
        policy['data']['requested_state']='idle'
        value=helper.development(self.client,self.state,**self.args,queue=True)
        self.assertIn('queue_receipt',value);self.assertFalse(value['paper_created'])

    def test_changed_checked_artifact_or_reviewed_file_refuses_queue(self):
        artifact=self.outcome['data']['completion_check']['artifacts'][0]
        Path(artifact['path']).write_text('Changed evidence')
        with self.assertRaisesRegex(ValueError,'artifact changed'):helper.development(self.client,self.state,**self.args,queue=True)
        artifact['sha256']=hashlib.sha256(Path(artifact['path']).read_bytes()).hexdigest()
        self.source['data']['reviewed_source_bindings']={'file:app/missing.py':{'sha256':'0'*64}}
        self.outcome['data']['completion_check']['result_sha256']=hashlib.sha256(json.dumps(self.source['data'],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        with self.assertRaisesRegex(ValueError,'Reviewed source changed'):helper.development(self.client,self.state,**self.args,queue=True)
        self.assertEqual(self.client.calls,[])

if __name__=='__main__':unittest.main()
