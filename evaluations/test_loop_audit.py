import sys, tempfile, unittest, io, json
from contextlib import redirect_stdout
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from loop_audit import audit, main


class LoopAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.loop={'kind':'loop','id':'review','version':1,'data':{'name':'Review','execution':{'type':'codex-heartbeat','automation_id':'review','status':'ACTIVE'},'refs':[]}}
        self.policy={'kind':'stack','id':'operating-policy','version':1,'data':{'schema_version':1,'requested_state':'active'}}
        self.state={'objects':[self.loop,self.policy]}
    def host(self,status):
        folder=self.root/'review';folder.mkdir(exist_ok=True)
        (folder/'automation.toml').write_text('status = "'+status+'"\nrrule = "FREQ=DAILY"')
    def test_stale_active_record_detected_without_mutation(self):
        self.host('PAUSED'); before=repr(self.state)
        result=audit(self.state,self.root)
        self.assertIn('host-status-mismatch',[f['code'] for f in result['findings']])
        self.assertEqual(repr(self.state),before)
    def test_missing_host_is_unknown_not_paused(self):
        result=audit(self.state,self.root)
        self.assertEqual(result['loops'][0]['host_status'],None)
        self.assertEqual(result['findings'][0]['code'],'host-unavailable')
    def test_active_host_outside_idle_detected(self):
        self.host('ACTIVE')
        result=audit(self.state,self.root)
        self.assertEqual(result['operating_state'],'active')
        self.assertIn('host-wakeup-outside-idle',[f['code'] for f in result['findings']])
    def test_idle_active_host_is_eligible_configuration(self):
        self.host('ACTIVE');self.policy['data']['requested_state']='idle'
        self.assertEqual(audit(self.state,self.root)['findings'],[])
    def test_matching_paused_record_is_clean(self):
        self.host('PAUSED');self.loop['data']['execution']['status']='PAUSED'
        self.assertEqual(audit(self.state,self.root)['findings'],[])
    def test_event_workflow_does_not_require_host_timer(self):
        self.loop['data']['execution']={'type':'codex-chat','trigger':'work-outcome','skill_id':'reviewer'}
        self.assertEqual(audit(self.state,self.root)['findings'],[])
    def test_invalid_host_id_cannot_escape_directory(self):
        self.loop['data']['execution']['automation_id']='../secret'
        self.assertEqual(audit(self.state,self.root)['findings'][0]['code'],'invalid-host-id')
    def test_stale_publication_cli_is_unverified_and_fails_closed(self):
        output=io.StringIO()
        with patch.object(sys,'argv',['loop_audit.py']), patch('routed_execution.PublishedClient.state',side_effect=ValueError('stale')), redirect_stdout(output):
            code=main()
        self.assertEqual(code,2)
        self.assertEqual(json.loads(output.getvalue())['status'],'unverified')


if __name__=='__main__': unittest.main()
