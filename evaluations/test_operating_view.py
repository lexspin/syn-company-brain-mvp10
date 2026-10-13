import http.client
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from operating_view import operating_view
from os_gateway import make_handler,decorate
from commands import stamp


class OperatingViewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'runtime');self.root=Path(self.temp.name)
        (self.root/'app').mkdir();(self.root/'data').mkdir()
        shutil.copy2(ROOT/'app/operating_policy.py',self.root/'app/operating_policy.py')
        self.agent={'kind':'agent','id':'worker','version':7,'data':{'name':'Worker','model':'gpt-6.1-sol','reasoning_effort':'medium'}}
        self.state={'objects':[self.agent],'worker_busy':True,'_view':{'asof':stamp(),'stale':False}}
        self.write()
    def tearDown(self):self.temp.cleanup()
    def write(self): (self.root/'data/state.json').write_text(json.dumps(self.state),encoding='utf-8')
    def test_legacy_setting_is_not_misreported_as_configured_or_idle_activity(self):
        v=operating_view(self.root,self.state)
        self.assertEqual(v['policy']['source'],'legacy-active');self.assertIsNone(v['policy']['requested_state'])
        self.assertTrue(v['activity']['worker_busy']);self.assertIsNone(v['agents'][0]['requested_state'])
        self.assertEqual(v['agents'][0]['model'],'gpt-6.1-sol');self.assertEqual(v['agents'][0]['reasoning_effort'],'medium')
        self.assertFalse((self.root/'runtime').exists())
    def test_global_restriction_wins_over_agent_active(self):
        self.state['objects'].append({'kind':'stack','id':'operating-policy','version':3,'data':{
            'name':'Operating policy','schema_version':1,'requested_state':'idle','idle':{'max_batch':2,'cooldown_seconds':300},'refs':[]}})
        self.agent['data']['operating_state']='active';self.write();v=operating_view(self.root,self.state)
        self.assertEqual(v['agents'][0]['effective_state'],'idle');self.assertEqual(v['policy']['version'],3)
        self.assertTrue(v['activity']['worker_busy'])
    def test_missing_configured_policy_fails_closed_and_activity_can_be_unknown(self):
        (self.root/'records/stack/operating-policy').mkdir(parents=True)
        self.state.pop('worker_busy');self.write();v=operating_view(self.root,self.state)
        self.assertEqual(v['policy']['effective_state'],'off');self.assertIsNone(v['activity']['worker_busy'])
    def test_agent_override_and_archived_filter(self):
        self.agent['data']['operating_state']='off'
        self.state['objects'].append({'kind':'agent','archived':True,'id':'old'})
        v=operating_view(self.root,self.state)
        self.assertEqual(len(v['agents']),1);self.assertEqual(v['agents'][0]['effective_state'],'off')
    def test_gateway_gets_local_projection_and_forwards_exact_control_once(self):
        calls=[]
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_POST(self):
                calls.append((self.path,dict(self.headers),json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b'{"version":4}')
        upstream=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
        gateway=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.root,upstream.server_port))
        threads=[]
        for server in (upstream,gateway):
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();threads.append(thread)
        try:
            c=http.client.HTTPConnection('127.0.0.1',gateway.server_port,timeout=3)
            c.request('GET','/api/os-operating');r=c.getresponse();data=json.loads(r.read());self.assertEqual(r.status,200)
            self.assertEqual(data['policy']['source'],'legacy-active');self.assertEqual(calls,[])
            c.request('GET','/operating-controls.js');r=c.getresponse();self.assertIn(b'CompanyBrainOperating',r.read())
            payload={'state':'idle','version':7,'agent_id':'worker'};ident='a'*32
            c.request('POST','/api/operating-state',json.dumps(payload),headers={'X-Brain-Token':'test','X-Brain-Request-ID':ident})
            r=c.getresponse();r.read();self.assertEqual(r.status,200);self.assertEqual(len(calls),1)
            self.assertEqual(calls[0][0],'/api/operating-state');self.assertEqual(calls[0][2],payload)
            self.assertEqual(calls[0][1]['X-Brain-Request-ID'],ident);c.close()
        finally:
            for server in (gateway,upstream):server.shutdown();server.server_close()
            for thread in threads:thread.join()
    def test_decoration_mounts_inside_token_scope_without_touching_connections(self):
        html=decorate('<meta charset="utf-8"><section id="workspace"></section><script>const token="test";document.body.prepend(W);</script>')
        self.assertIn('window.CompanyBrainOperating.mount(token)',html)
        self.assertEqual(html.count('id="operating-controls"'),1)
        self.assertIn('src="/operating-controls.js"',html)


if __name__=='__main__':unittest.main()
