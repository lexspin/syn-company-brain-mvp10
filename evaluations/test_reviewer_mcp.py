"""Read-only reviewer transport and authority tests; model-free fixtures."""
from datetime import datetime, timezone, timedelta
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from memory_mcp import MemoryHub, serve, TOOL_NAMES, REVIEW_NAMES, CANONICAL_ROOT
from native_activity import emit_activity


class ReviewerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        body='Verify the actual output before reuse.'
        row=lambda kind,id,data:dict(kind=kind,id=id,version=1,archived=False,data=data)
        self.state={'root':str(self.root),'_view':{'asof':datetime.now(timezone.utc).isoformat(),'stale':False},
            'memory_freshness':{'outcome':{'current':True}},'objects':[
                row('project','lab',{'name':'Lab','refs':['skill:checker','memory:candidate']}),
                row('skill','checker',{'name':'Checker','instructions':body,'refs':['project:lab']}),
                row('memory','outcome',{'name':'Outcome','content':'Checked receipt','refs':['project:lab']}),
                row('memory','candidate',{'name':'Receipt verification','type':'learning-candidate','status':'candidate',
                    'proposed_instructions':body,'candidate_sha256':hashlib.sha256(body.encode()).hexdigest(),
                    'target':{'kind':'skill-update','id':'checker','version':1},'source_bindings':{'memory:outcome':1},'refs':['project:lab']})]}
        self.requests=[];owner=self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.requests.append((self.command,self.path));payload=json.dumps(owner.state).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
            def do_POST(self):owner.requests.append((self.command,self.path));self.send_error(405)
            def log_message(self,*args):pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
        self.hub=MemoryHub(self.base,native_read_only=True)
        self.patch=patch('memory_mcp.CANONICAL_ROOT',self.root);self.patch.start()

    def tearDown(self):
        self.patch.stop();self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()

    def test_actual_review_helpers_no_writes(self):
        emit_activity(self.root,dict(event_id='event',task_id='task',chat_id='fixture-chat',type='started',title='Checked fixture',provenance='unit fixture',area_refs=['skill:checker']))
        # SQLite mode=ro may create transient WAL reader sidecars; durable data
        # and event content must stay unchanged. Sidecars are not Brain writes.
        snapshot=lambda:{str(p.relative_to(self.root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file() and not p.name.endswith(('-shm','-wal'))}
        before=snapshot()
        learning=self.hub.call(REVIEW_NAMES[0],{'project_id':'lab','query':'verification','limit':1})
        self.assertEqual(learning['candidates'][0]['id'],'candidate');self.assertEqual(learning['candidates'][0]['drift'],[])
        curation=self.hub.call(REVIEW_NAMES[1],{'project_id':'lab','query':'checker','limit':1})
        self.assertEqual(curation['recommendations'][0]['ref'],'skill:checker')
        self.assertEqual(curation['telemetry']['tasks_inspected'],1)
        self.assertEqual(before,snapshot());self.assertTrue(all(method=='GET' and path=='/api/state' for method,path in self.requests))
        from native_activity import read_events
        self.assertEqual([event['event_id'] for event in read_events(self.root,'task')['events']],['event'])

    def test_scope_cannot_list_or_invoke_reviewers(self):
        scoped=MemoryHub(self.base,[{'kind':'project','id':'lab','version':1}])
        requests=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{}},{'jsonrpc':'2.0','method':'notifications/initialized'},
            {'jsonrpc':'2.0','id':2,'method':'tools/list'},
            {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':REVIEW_NAMES[0],'arguments':{'project_id':'lab'}}}]
        sink=io.StringIO();serve(scoped,io.StringIO('\n'.join(map(json.dumps,requests))),sink)
        replies=[json.loads(line)['result'] for line in sink.getvalue().splitlines()]
        self.assertEqual([t['name'] for t in replies[1]['tools']],TOOL_NAMES);self.assertTrue(replies[2]['isError'])
        self.assertEqual(self.requests,[])
        with self.assertRaises(ValueError):MemoryHub(self.base,[],native_read_only=True)

    def test_bad_args_and_limits_fail_before_reads(self):
        for args in [{},{'project_id':''},{'project_id':'../lab'},{'project_id':'lab','root':str(self.root)},
            {'project_id':'lab','query':'x'*1001},{'project_id':'lab','query':None},
            *[{'project_id':'lab','limit':n} for n in [0,33,True,'1']]]:
            for name in REVIEW_NAMES:
                with self.subTest(name=name,args=args),self.assertRaises(ValueError):self.hub.call(name,args)
        self.assertEqual(self.requests,[])

    def test_root_identity_staleness_missing_project_and_unknown_tool(self):
        self.state['root']=str(self.root/'other')
        with patch('native_activity.read_activity',side_effect=AssertionError('Must not read local telemetry')):
            with self.assertRaisesRegex(ValueError,'canonical'):self.hub.call(REVIEW_NAMES[1],{'project_id':'lab'})
        self.state['root']=str(self.root);self.state['_view']['stale']=True
        with self.assertRaisesRegex(ValueError,'stale'):self.hub.call(REVIEW_NAMES[0],{'project_id':'lab'})
        self.state['_view']['stale']=False;self.state['_view']['asof']=(datetime.now(timezone.utc)-timedelta(seconds=40)).isoformat()
        with self.assertRaises(ValueError):self.hub.call(REVIEW_NAMES[0],{'project_id':'lab'})
        self.state['_view']['asof']=datetime.now(timezone.utc).isoformat()
        for name in REVIEW_NAMES:
            with self.assertRaises(ValueError):self.hub.call(name,{'project_id':'missing'})
        with self.assertRaises(ValueError):self.hub.call('promote_skill',{'project_id':'lab'})

    def test_real_stdio_handshake_list_success_and_error(self):
        self.state['root']=str(CANONICAL_ROOT)
        requests=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25'}},
            {'jsonrpc':'2.0','method':'notifications/initialized'},{'jsonrpc':'2.0','id':2,'method':'tools/list'},
            *[{'jsonrpc':'2.0','id':i+3,'method':'tools/call','params':{'name':name,'arguments':{'project_id':'lab','limit':1}}} for i,name in enumerate(REVIEW_NAMES)],
            {'jsonrpc':'2.0','id':5,'method':'tools/call','params':{'name':REVIEW_NAMES[0],'arguments':{'project_id':'lab','unexpected':True}}}]
        result=subprocess.run([sys.executable,str(ROOT/'app/memory_mcp.py'),'--base',self.base,'--native-read-only'],input='\n'.join(map(json.dumps,requests))+'\n',capture_output=True,text=True,encoding='utf-8',timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        replies=[json.loads(line)['result'] for line in result.stdout.splitlines()]
        self.assertEqual([t['name'] for t in replies[1]['tools']],TOOL_NAMES+REVIEW_NAMES)
        for tool in replies[1]['tools'][-2:]:
            self.assertEqual(tool['inputSchema']['required'],['project_id']);self.assertFalse(tool['inputSchema']['additionalProperties']);self.assertTrue(tool['annotations']['readOnlyHint'])
        self.assertFalse(replies[2]['isError']);self.assertFalse(replies[3]['isError']);self.assertTrue(replies[4]['isError'])


if __name__=='__main__':unittest.main()
