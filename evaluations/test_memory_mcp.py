import io
import json
import sys
from pathlib import Path
import subprocess
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from datetime import datetime,timezone,timedelta
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from memory_mcp import MemoryHub,serve,preflight,TOOL_NAMES
from codex_runtime import command,parse
from routing_context import cards,relevant_connections

class MemoryTests(unittest.TestCase):
 def setUp(self):
  self.state={'_view':{'asof':datetime.now(timezone.utc).isoformat(),'stale':False},'objects':[
   {'kind':'memory','id':'policy','version':1,'data':{'name':'Policy','content':'Use whole pounds.','source':'Owner'},'archived':False},
   {'kind':'memory','id':'other','version':1,'data':{'name':'Other','content':'Private unrelated facts.'},'archived':False},
   {'kind':'skill','id':'writer','version':2,'data':{'name':'Writer','instructions':'Cite sources.'},'archived':False},
   {'kind':'project','id':'lab','version':1,'data':{'name':'Lab','path':str(ROOT),'scope':'Research'},'archived':False}],
   'memory_freshness':{'policy':{'current':True},'other':{'current':True}}}
  state=self.state
  class Handler(BaseHTTPRequestHandler):
   def do_GET(self):
    if self.path!='/api/state':self.send_error(404);return
    body=json.dumps(state).encode();self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
   def log_message(self,*args):pass
  self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
  self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  self.base='http://127.0.0.1:'+str(self.server.server_port)
  self.allowed=[{k:r[k] for k in ('kind','id','version')} for r in self.state['objects'] if r['id']!='other']
  self.hub=MemoryHub(self.base,self.allowed)
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join()
 def test_current_exact_reads_and_search(self):
  self.assertEqual(self.hub.call('get_knowledge',{'id':'policy'})['record']['version'],1)
  self.assertEqual(self.hub.call('get_skill',{'id':'writer'})['record']['data']['instructions'],'Cite sources.')
  self.assertEqual(self.hub.call('get_project',{'id':'lab'})['record']['data']['scope'],'Research')
  self.assertEqual(self.hub.call('search_knowledge',{'query':'pounds'})['records'][0]['id'],'policy')
 def test_default_scope_is_closed_and_explicit_native_mode_is_read_only(self):
  with self.assertRaises(ValueError):MemoryHub(self.base).call('get_knowledge',{'id':'policy'})
  native=MemoryHub(self.base,native_read_only=True)
  self.assertEqual(native.call('get_knowledge',{'id':'other'})['record']['id'],'other')
  self.assertEqual(native.call('get_skill',{'id':'writer'})['record']['version'],2)
  with self.assertRaises(ValueError):native.call('read_file',{'path':'anything'})
  with self.assertRaises(ValueError):native.call('get_chat',{'id':'any'})
  with self.assertRaises(ValueError):MemoryHub(self.base,self.allowed,native_read_only=True)
 def test_stdio_requires_explicit_scope_mode(self):
  result=subprocess.run([sys.executable,str(ROOT/'app/memory_mcp.py')],capture_output=True,text=True,timeout=3)
  self.assertNotEqual(result.returncode,0)
 def test_cannot_read_unrelated_or_newer_version(self):
  with self.assertRaises(ValueError):self.hub.call('get_knowledge',{'id':'other'})
  self.state['objects'][0]['version']=2
  with self.assertRaises(ValueError):self.hub.call('get_knowledge',{'id':'policy'})
 def test_stale_or_archived_source_is_excluded(self):
  self.state['memory_freshness']['policy']['current']=False
  self.assertEqual(self.hub.call('search_knowledge',{'query':'pounds'})['records'],[])
  with self.assertRaises(ValueError):self.hub.call('get_knowledge',{'id':'policy'})
 def test_preflight_confirms_all_dependencies_and_checks_age(self):
  self.assertEqual(preflight(self.allowed,self.base)['status'],'available')
  self.state['_view']['asof']=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
  with self.assertRaises(ValueError):preflight(self.allowed,self.base)
 def test_write_routes_and_path_traversal_not_supported(self):
  for name,args in [('save',{}),('get_knowledge',{'id':'../../secret'}),('get_skill',{'id':'writer','path':'C:/secret'})]:
   with self.assertRaises(ValueError):self.hub.call(name,args)
  for base in ['https://example.com','http://localhost:14699','http://127.0.0.1:14699/private','http://127.0.0.1:14699?x=1']:
   with self.assertRaises(ValueError):MemoryHub(base)
 def test_real_stdio_process_handshake_list_and_call(self):
  self.state['objects'][0]['data']['content']='Alex’s thesis — în română: Ω.'
  requests=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'test','version':'1'}}},
   {'jsonrpc':'2.0','method':'notifications/initialized'},
   {'jsonrpc':'2.0','id':2,'method':'tools/list'},
   {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'get_knowledge','arguments':{'id':'policy'}}},
   {'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'save','arguments':{}}}]
  import os
  result=subprocess.run([sys.executable,str(ROOT/'app/memory_mcp.py'),'--base',self.base,'--scope-json',json.dumps(self.allowed)],input='\n'.join(map(json.dumps,requests))+'\n',capture_output=True,text=True,encoding='utf-8',env={**os.environ,'PYTHONUTF8':'0','PYTHONIOENCODING':'cp1252'},timeout=5)
  self.assertEqual(result.returncode,0,result.stderr)
  results=[json.loads(line) for line in result.stdout.splitlines()]
  self.assertEqual(results[0]['result']['serverInfo']['name'],'company_brain_memory')
  self.assertEqual([t['name'] for t in results[1]['result']['tools']],TOOL_NAMES)
  self.assertFalse(results[2]['result']['isError']);self.assertTrue(results[3]['result']['isError'])
  self.assertEqual(results[2]['result']['structuredContent']['record']['data']['content'],'Alex’s thesis — în română: Ω.')
 def test_uninitialized_read_is_rejected(self):
  sink=io.StringIO();serve(self.hub,io.StringIO(json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/list'})+'\n'),sink)
  self.assertIn('error',json.loads(sink.getvalue()))
 @patch('codex_runtime.select_client',return_value={'path':'codex.exe','version':'codex-cli 0.162.0'})
 def test_cli_only_enables_scoped_memory_server(self,_):
  args=command(memory_context=self.allowed)
  self.assertIn('--ignore-user-config',args)
  self.assertIn('features.shell_tool=false',args);self.assertIn('features.apps=false',args)
  self.assertTrue(any(x.startswith('mcp_servers.company_brain_memory.args=') for x in args))
  self.assertFalse(any('company-brain-local' in x for x in args))
 def test_tool_receipts_survive_runtime_parse(self):
  result=parse('\n'.join(map(json.dumps,[{'type':'item.completed','item':{'type':'mcp_tool_call','server':'company_brain_memory','tool':'get_knowledge','status':'completed','arguments':{'id':'policy'}}},{'type':'item.completed','item':{'type':'agent_message','text':'Answer'}},{'type':'turn.completed'}])),0)
  self.assertEqual(result['tool_calls'][0]['tool'],'get_knowledge')

if __name__=='__main__':unittest.main()
