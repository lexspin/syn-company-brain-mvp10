import copy
import json
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from http.server import ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from os_control import overview, record_link
from os_preview import make_handler
from loop_policy import decide


def row(kind,identity,data,version=1,archived=0):
    return dict(kind=kind,id=identity,data=data,version=version,archived=archived)


class ExecutiveView(unittest.TestCase):
    def setUp(self):
        self.state={'objects':[row('loop','test',{'name':'Test','steps':[{'tool':'retrieve'}],'refs':[]})],
                    'memory_freshness':{},'worker_busy':False,'_view':{'stale':False}}

    def test_empty_queue_is_not_passive_success(self):
        view=overview(self.state)
        self.assertEqual(view['counts']['completed'],0)
        self.assertEqual(view['workflows'][0]['status'],'Configured')
        self.assertIn('not established',view['workflows'][0]['schedule_evidence'])

    def test_completed_without_real_link_is_attention(self):
        self.state['objects'].append(row('memory','request',{'type':'native-work-request','loop_id':'test','request_state':'completed','result_ref':'absent'}))
        self.assertEqual(len(overview(self.state)['attention']),1)

    def test_bound_result_is_recorded_not_semantically_verified(self):
        self.state['objects'] += [row('memory','result',{'refs':['loop:test']}),row('memory','request',{
            'type':'native-work-request','loop_id':'test','request_state':'completed','result_ref':'result',
            'completion_evidence':'checked','claimant':'worker','claimed_at':'then','completed_at':'now'})]
        view=overview(self.state)
        self.assertFalse(view['attention'])
        self.assertEqual(view['workflows'][0]['outcomes'][0]['evidence'],'Result and checks recorded')
        self.state['objects'][1]['archived']=1
        self.assertTrue(overview(self.state)['attention'])

    def test_stale_request_and_missing_skill_reported(self):
        self.state['objects'][0]['data']['execution']={'type':'codex-chat','skill_id':'missing'}
        self.state['objects'].append(row('memory','request',{'type':'native-work-request','loop_id':'test','loop_version':0,'request_state':'queued'}))
        self.assertEqual(len(overview(self.state)['attention']),2)

    def test_projection_does_not_mutate_state_and_encodes_links(self):
        before=copy.deepcopy(self.state);overview(self.state)
        self.assertEqual(before,self.state)
        self.assertIn('%22',record_link('memory','a"b'))


class LoopPolicy(unittest.TestCase):
    def setUp(self):
        self.s=json.loads((Path(__file__).resolve().parents[1]/'skills/company-brain-loop-engineering/references/observation.json').read_text())

    def test_safe_retry_bounded(self):
        self.assertEqual(decide(self.s)['action'],'retry')
        self.s['attempt']=3
        self.assertEqual(decide(self.s)['action'],'stop')

    def test_unknown_effect_never_replayed_even_cancelled(self):
        self.s.update(outcome='uncertain',cancelled=True)
        self.assertEqual(decide(self.s)['action'],'reconcile')

    def test_side_effect_retry_needs_reconciliation(self):
        self.s['effect']='non-idempotent'
        self.assertEqual(decide(self.s)['action'],'reconcile')

    def test_quality_and_receipt_are_both_required(self):
        self.s.update(outcome='succeeded',acceptance_passed=True)
        self.assertEqual(decide(self.s)['action'],'review')
        self.s['receipt_verified']=True
        self.assertEqual(decide(self.s)['action'],'complete')

    def test_source_and_authority_gates(self):
        self.s['sources_current']=False
        self.assertEqual(decide(self.s)['action'],'replan')
        self.s['authority_current']=False
        self.assertEqual(decide(self.s)['action'],'blocked')

    def test_backoff_cannot_exceed_deadline(self):
        self.s['elapsed_seconds']=119
        self.assertEqual(decide(self.s)['action'],'stop')

    def test_bad_flags_and_unbounded_budget_rejected(self):
        for field,value in [('cancelled','false'),('max_attempts',0),('attempt',True),('effect','unknown')]:
            with self.subTest(field=field):
                s=dict(self.s);s[field]=value
                with self.assertRaises(ValueError):decide(s)


class PreviewHTTP(unittest.TestCase):
    def test_live_read_only_boundary_and_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'data').mkdir()
            state={'root':str(root),'objects':[],'_view':{'asof':datetime.now(timezone.utc).isoformat()}}
            path=root/'data/state.json';path.write_text(json.dumps(state))
            server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(root))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                with urllib.request.urlopen(base+'/api/os-overview') as response:
                    self.assertEqual(json.load(response)['counts']['queued'],0)
                for request,status in [(urllib.request.Request(base+'/api/save',data=b'{}'),405),
                                       (urllib.request.Request(base+'/',headers={'Host':'evil.example'}),403)]:
                    with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
                    self.assertEqual(error.exception.code,status)
                    error.exception.close()
                state['root']='wrong';path.write_text(json.dumps(state))
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(base+'/api/os-overview')
                self.assertEqual(error.exception.code,503)
                error.exception.close()
                self.assertFalse((root/'store').exists())
            finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
