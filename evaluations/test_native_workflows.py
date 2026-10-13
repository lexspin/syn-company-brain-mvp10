import unittest
import test_brain


class NativeWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.f=test_brain.BrainTests();self.f.setUp();self.b=self.f.b
        self.data={'name':'Research intake','instructions':'Read, compare, archive and verify.',
                   'execution':{'type':'codex-chat','trigger':'research-request','skill_id':'writer'},
                   'refs':['skill:writer']}

    def tearDown(self):self.f.tearDown()

    def test_registered_native_workflow_cannot_pretend_to_execute_locally(self):
        self.b.save('loop','native-research',self.data)
        with self.assertRaisesRegex(ValueError,'native Codex chats'):self.b.snapshot('native-research')

    def test_rejects_broken_skill_and_fake_trigger(self):
        for change in ({'skill_id':'missing'},{'trigger':'arbitrary-watcher'}):
            data=self.data|{'execution':self.data['execution']|change}
            with self.assertRaises(ValueError):self.b.save('loop','native-research',data)

    def test_rejects_local_steps_and_missing_skill_connection(self):
        for change in ({'steps':[{'tool':'draft'}]},{'refs':[]}):
            with self.assertRaises(ValueError):self.b.save('loop','native-research',self.data|change)

    def test_request_claim_conflict_and_completion_evidence(self):
        self.b.save('loop','native-research',self.data)
        data={'name':'Research request','type':'native-work-request','status':'candidate','content':'Review source',
              'source':'Owner request','loop_id':'native-research','loop_version':1,'refs':['loop:native-research'],'request_state':'queued'}
        self.b.save('memory','request',data)
        claim=data|{'request_state':'running','claimant':'fixture-worker','claimed_at':'2026-10-10T00:00:00Z'}
        self.b.save('memory','request',claim,1)
        with self.assertRaises(ValueError):self.b.save('memory','request',claim,1)
        with self.assertRaises(ValueError):self.b.save('memory','request',claim|{'request_state':'completed'},2)
        policy=self.b.get('memory','policy');self.b.save('memory','policy',policy['data']|{'refs':['loop:native-research']},policy['version'])
        self.b.save('memory','request',claim|{'request_state':'completed','result_ref':'policy','completion_evidence':'Fixture checked saved source','completed_at':'2026-10-10T00:01:00Z'},2)
        self.assertNotIn('request',[m['id'] for m in self.b.current_memories()])

    def request(self):
        self.b.save('loop','native-research',self.data)
        data={'name':'Request','type':'native-work-request','status':'candidate','content':'Fixture','source':'Test',
              'loop_id':'native-research','loop_version':1,'refs':['loop:native-research'],'request_state':'queued'}
        self.b.save('memory','request',data)
        return data

    def test_cannot_skip_claim_or_create_running(self):
        data=self.request()
        done=data|{'request_state':'completed','result_ref':'policy','completion_evidence':'Assertion','completed_at':'now'}
        with self.assertRaisesRegex(ValueError,'transition'):self.b.save('memory','request',done,1)
        with self.assertRaisesRegex(ValueError,'start queued'):self.b.save('memory','new',data|{'request_state':'running','claimant':'a','claimed_at':'now'})

    def test_stale_or_archived_workflow_blocks_claim_but_allows_failure(self):
        data=self.request();self.b.save('loop','native-research',self.data,1,True)
        with self.assertRaisesRegex(ValueError,'changed or was archived'):self.b.save('memory','request',data|{'request_state':'running','claimant':'a','claimed_at':'now'},1)
        self.b.save('memory','request',data|{'request_state':'failed','failure_reason':'Workflow archived'},1)
        with self.assertRaisesRegex(ValueError,'transition'):self.b.save('memory','request',data,2)

    def test_owner_binding_and_type_cannot_be_rewritten(self):
        data=self.request();claim=data|{'request_state':'running','claimant':'a','claimed_at':'now'};self.b.save('memory','request',claim,1)
        for change in ({'claimant':'b'},{'loop_version':2},{'type':'ordinary-memory'}):
            with self.assertRaises(ValueError):self.b.save('memory','request',claim|change,2)

    def test_unrelated_result_and_midflight_workflow_change_block_completion(self):
        data=self.request();claim=data|{'request_state':'running','claimant':'a','claimed_at':'now'};self.b.save('memory','request',claim,1)
        done=claim|{'request_state':'completed','result_ref':'policy','completion_evidence':'Checked','completed_at':'later'}
        with self.assertRaisesRegex(ValueError,'link to'):self.b.save('memory','request',done,2)
        p=self.b.get('memory','policy');self.b.save('memory','policy',p['data']|{'refs':['loop:native-research']},p['version'])
        self.b.save('loop','native-research',self.data|{'instructions':'New scope'},1)
        with self.assertRaisesRegex(ValueError,'changed'):self.b.save('memory','request',done,2)
