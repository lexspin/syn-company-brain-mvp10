"""Actual callback, checker, HTTP and retention gates using isolated fixtures."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'app'))
from native_activity import read_activity
from native_execution import AlreadyRecorded
from routed_execution import RoutedExecution, PublishedClient, RetentionPending, evaluate_contract


class Client:
    def __init__(self, state, receipt):
        self.published, self.saved, self.reads = state, receipt, []
    def state(self):
        self.reads.append('state');return deepcopy(self.published)
    def receipt(self, id):
        self.reads.append('receipt:'+id);return deepcopy(self.saved)
    def knowledge(self, id):
        self.reads.append('get:'+id)
        return {'record': deepcopy(next(row for row in self.published['objects'] if row['kind']=='memory' and row['id']==id))}
    def search(self, id):
        self.reads.append('search:'+id)
        return {'records': [dict(id=row['id'], version=row['version']) for row in self.published['objects'] if row['kind']=='memory' and row['id']==id and self.published['memory_freshness'].get(id,{}).get('current')]}


class RoutedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'runtime');self.root=Path(self.temp.name).resolve()
        (self.root/'runtime').mkdir();self.project=self.root/'product';self.project.mkdir()
        self.source=self.project/'source.txt';self.source.write_text('Original checked source.',encoding='utf-8')
        self.output=self.project/'result.md';self.output.write_text('Checked actual output.',encoding='utf-8')
        self.hash=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        self.plan={'outcome':'Verify real output and retain its checked result','request_source':'native-chat:fixture-chat',
            'project_root':str(self.project),'skills':['skill:checker@1'],'tools':['test-output','canonical-archive'],
            'attempt':1,'max_attempts':2,'elapsed_seconds':1,'timeout_seconds':60,'uncertain_effect':False,
            'sources':[{'path':str(self.source),'sha256':self.hash(self.source)}],
            'artifact_paths':[str(self.output)],'result_path':str(self.output),'acceptance_id':'accept',
            'artifacts':[], 'requirements':[
                {'id':'check-output','category':'work','description':'Output bytes meet the intended requirement','depends_on':[],'status':'unknown','evidence':[]},
                {'id':'accept','category':'acceptance','description':'Work and retained artifacts meet final acceptance','depends_on':['check-output'],'status':'unknown','evidence':[]}]}
        self.contract=self.root/'runtime'/'plan.json';self.evidence=self.root/'runtime'/'evidence.json';self.write_plan()
        row=lambda kind,id,data:dict(kind=kind,id=id,version=1,archived=False,data=data)
        self.state={'root':str(self.root),'_view':{'asof':datetime.now(timezone.utc).isoformat(),'stale':False},'memory_freshness':{},'objects':[
            row('stack','operating-policy',{'schema_version':1,'requested_state':'active'}),
            row('project','lab',{'name':'Lab','path':str(self.project),'refs':['skill:checker']}),
            row('skill','checker',{'name':'Checker','instructions':'Verify output.','refs':['project:lab']})]}
        self.receipt={'id':'a'*32,'ok':True,'action':'archive-research','state':'completed','result':{}}
        self.client=Client(self.state,self.receipt);self.root_patch=patch('routed_execution.CANONICAL_ROOT',self.root);self.root_patch.start()
        self.calls=[]

    def tearDown(self):
        self.root_patch.stop();self.temp.cleanup()

    def write_plan(self):
        self.contract.write_text(json.dumps(self.plan),encoding='utf-8')

    def test_changed_context_is_rejected_before_stage_callback(self):
        for mode in ('source', 'policy', 'skill', 'contract', 'in-memory-contract'):
            original_state=deepcopy(self.state); original_source=self.source.read_bytes()
            with self.subTest(mode=mode), self.route('drift-'+mode) as run:
                if mode=='source': self.source.write_text('Changed evidence.',encoding='utf-8')
                elif mode=='policy': self.state['objects'][0]['data']['requested_state']='off'
                elif mode=='skill': self.state['objects'][2]['data']['instructions']='Different procedure'
                elif mode=='contract': self.contract.write_text('{}',encoding='utf-8')
                else: run.plan['outcome']='Changed scope'
                with self.assertRaises(ValueError):
                    run.stage('check-output','Must not execute',lambda:self.calls.append(mode),check=lambda value:True)
                self.assertEqual(self.calls,[])
            self.state.clear();self.state.update(original_state);self.source.write_bytes(original_source);self.write_plan()

    def test_windows_line_endings_match_archived_text_without_weakening_byte_hashes(self):
        self.output.write_bytes(b'Checked actual output.\r\nSecond line.\r\n')
        with self.route('windows-newlines') as run:
            run.stage('check-output','Check actual multiline output',self.output.read_bytes,
                      check=lambda value:value==b'Checked actual output.\r\nSecond line.\r\n')
            run.accept('accept','Accept checked multiline result',lambda:self.output.exists(),requires=('check-output',))
            self.retain_fixture();self.finish(run)
        self.assertTrue(run.gate_checks['retained_memory'])

    def route(self, task='task', **kwargs):
        return RoutedExecution(self.root,task,'Checked fixture task',project_id='lab',skill_versions={'checker':1},
            contract_path=self.contract,chat_id='fixture-chat',client=self.client,**kwargs)

    def bind_agent(self, mode='active'):
        agent = dict(kind='agent', id='manager', version=1, archived=False,
                     data={'name':'Fixture manager', 'level':'manager', 'operating_state':mode,
                           'skills':['checker'], 'refs':[]})
        self.state['objects'].append(agent)
        self.plan['agent_binding'] = {'id':'manager', 'version':1, 'role':'manager',
                                      'skill_versions':{'checker':1}}
        self.write_plan()
        return agent

    def test_selected_agent_off_idle_unknown_archived_refuse_before_callback_or_start(self):
        agent = self.bind_agent()
        for index, update in enumerate([{'data':agent['data'] | {'operating_state':'off'}},
                                       {'data':agent['data'] | {'operating_state':'idle'}},
                                       {'archived':True}, {'id':'different-manager'}]):
            original = deepcopy(agent);agent.update(update)
            with self.subTest(index=index), self.assertRaises(ValueError):
                with self.route('agent-refused-'+str(index), agent_id='manager', agent_version=1):
                    self.calls.append('callback')
            agent.clear();agent.update(original)
        self.assertEqual(self.calls, [])
        self.assertEqual(read_activity(self.root), [])
        self.state['objects'][0]['data']['requested_state']='idle'
        with self.assertRaises(ValueError):
            with self.route('global-idle-agent-active',agent_id='manager',agent_version=1):
                self.calls.append('callback')
        self.assertEqual(self.calls, []);self.assertEqual(read_activity(self.root), [])

    def test_current_role_bound_completion_and_verified_retention_ref_only_change(self):
        agent = self.bind_agent()
        with self.route(agent_id='manager', agent_version=1) as run:
            self.execute(run);self.retain_fixture()
            # The separately accepted result now includes a reciprocal agent
            # link; ref-only upkeep is not a changed role instruction/model.
            memory = next(row for row in self.state['objects'] if row['kind']=='memory')
            memory['data']['refs'].append('agent:manager')
            self.receipt['result']['data'] = deepcopy(memory['data'])
            agent['version'] += 1;agent['data']['refs'].append('memory:retained')
            self.finish(run)
        self.assertTrue(run.gate_checks['agent_bound'])
        self.assertEqual(run.gate_checks['agent_ref'], 'agent:manager')
        self.assertEqual(run.gate_checks['agent_version'], 1)
        self.assertEqual(run.gate_checks['agent_linked_skills'], 1)
        self.assertEqual(read_activity(self.root)[0]['agent_id'], 'manager')

    def test_agent_role_version_skills_and_unbound_metadata_refuse_at_admission(self):
        agent = self.bind_agent()
        for index, change in enumerate([
                lambda:agent.update(version=2), lambda:self.plan['agent_binding'].update(role='worker'),
                lambda:self.plan['agent_binding'].update(skill_versions={}),
                lambda:self.state['objects'][2].update(version=2)]):
            previous_state, previous_plan = deepcopy(self.state), deepcopy(self.plan)
            change();self.write_plan()
            with self.subTest(index=index), self.assertRaises(ValueError):
                with self.route('agent-shape-'+str(index), agent_id='manager', agent_version=1):
                    self.calls.append(1)
            self.state.clear();self.state.update(previous_state)
            agent=next(row for row in self.state['objects'] if row['kind']=='agent')
            self.plan=previous_plan;self.write_plan()
        with self.assertRaises(ValueError):
            with self.route('unselected-role'):self.calls.append(1)
        with self.assertRaises(ValueError):self.route('no-expected-version',agent_id='manager')
        self.assertEqual(self.calls, []);self.assertEqual(read_activity(self.root), [])

    def test_agent_drift_before_callback_and_after_acceptance_is_checked(self):
        agent = self.bind_agent()
        with self.route('changed-before-stage',agent_id='manager',agent_version=1) as run:
            agent['version'] += 1
            with self.assertRaisesRegex(ValueError, 'version drifted'):
                run.stage('check-output','Check actual output',lambda:self.calls.append(1),check=lambda _:True)
        self.assertEqual(self.calls, [])
        agent['version']=1
        with self.route('changed-after-accept',agent_id='manager',agent_version=1) as run:
            self.execute(run);self.retain_fixture();agent['data']['model']='different-model'
            with self.assertRaisesRegex(ValueError, 'semantics changed'):self.finish(run)
        self.assertTrue(all(row['status']=='failed' for row in read_activity(self.root)))

    def test_agent_linked_skill_semantic_drift_and_binding_retarget_are_rejected(self):
        self.bind_agent()
        with self.route('skill-drift',agent_id='manager',agent_version=1) as run:
            self.execute(run);self.retain_fixture()
            skill = next(row for row in self.state['objects'] if row['kind']=='skill')
            skill['data']['instructions']='Changed after actual acceptance'
            with self.assertRaisesRegex(ValueError, 'semantics changed'):self.finish(run)
        skill['data']['instructions']='Verify output.';skill['version']=1
        with self.route('retarget',agent_id='manager',agent_version=1) as run:
            self.execute(run);self.retain_fixture()
            final=json.loads(self.evidence.read_text(encoding='utf-8'))
            final['agent_binding']['role']='worker';self.evidence.write_text(json.dumps(final),encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'retargeted'):self.finish(run)

    def test_role_version_drift_is_rejected_again_at_completion(self):
        agent=self.bind_agent()
        with self.route('final-role-version',agent_id='manager',agent_version=1) as run:
            self.execute(run);self.retain_fixture();agent['version']+=1
            with self.assertRaisesRegex(ValueError, 'version drifted'):self.finish(run)
        self.assertEqual(read_activity(self.root)[0]['status'], 'failed')

    def test_task_support_skills_may_be_outside_role_links_without_switching_host_model(self):
        agent=self.bind_agent()
        agent['data'].update(skills=['domain-role'],model='configured-model')
        self.state['objects'].append(dict(kind='skill',id='domain-role',version=1,archived=False,
                                         data={'name':'Domain role','instructions':'Scoped role directions','refs':[]}))
        self.plan['agent_binding']['skill_versions']={'domain-role':1};self.write_plan()
        with self.route('support-skill',agent_id='manager',agent_version=1,model='actual-host-model') as run:
            self.execute(run);self.retain_fixture();self.finish(run)
        self.assertEqual(run.start['model'], 'actual-host-model')
        self.assertEqual(run.gate_checks['agent_linked_skills'], 1)

    def execute(self, run):
        run.stage('check-output','Check actual output',lambda:self.output.read_text(encoding='utf-8'),
            check=lambda value:value=='Checked actual output.',reads=[{'label':'Actual result','reference':str(self.output)}])
        run.accept('accept','Compare final result',lambda:self.output.exists(),requires=('check-output',))

    def retain_fixture(self):
        # Represents a separately completed canonical archive action. The wrapper
        # itself receives only the read client and cannot create these effects.
        content=self.output.read_text(encoding='utf-8')
        memory=dict(kind='memory',id='retained',version=1,archived=False,data={
            'name':'Checked result','content':content,'status':'accepted','refs':['project:lab','skill:checker'],
            'capture':{'kind':'supplied-research','provenance':{'chat_id':'fixture-chat'}}})
        links=[]
        for row in self.state['objects']:
            if (row['kind'],row['id']) in {('project','lab'),('skill','checker')}:
                row['version']+=1;row['data']['refs'].append('memory:retained');links.append({k:row[k] for k in ['kind','id','version']})
        self.state['objects'].append(memory);self.state['memory_freshness']['retained']={'current':True}
        self.receipt['result']=deepcopy(memory)|{'capture_status':'created','updated_links':links}
        evidence=deepcopy(self.plan);evidence['artifacts']=[{'path':str(self.output),'sha256':self.hash(self.output)}]
        for r in evidence['requirements']:r.update(status='passed',evidence=[0])
        self.evidence.write_text(json.dumps(evidence),encoding='utf-8')

    def finish(self, run):
        run.complete(evidence_path=self.evidence,receipt_id='a'*32)

    def test_actual_checked_completion_and_ref_only_archive_versions(self):
        with self.route() as run:
            self.execute(run);self.retain_fixture();self.finish(run)
        self.assertEqual(read_activity(self.root)[0]['status'],'completed')
        self.assertEqual(self.client.reads,['state','state','state','receipt:'+'a'*32,'state','get:retained','search:retained'])
        self.assertTrue(run.gate_checks['bounded_search'])
        self.assertFalse(run.gate_checks['agent_bound'])
        self.assertTrue(all(row['version']==2 for row in self.state['objects'] if row['kind'] in {'project','skill'}))

    def test_off_idle_invalid_policy_refuse_before_any_work_or_telemetry(self):
        for state in ['off','idle','broken']:
            self.state['objects'][0]['data']['requested_state']=state
            with self.subTest(state=state),self.assertRaises(ValueError):
                with self.route(state):self.calls.append('work')
        self.assertEqual(self.calls,[]);self.assertEqual(read_activity(self.root),[])
        self.state['objects'][0]['data']['requested_state']='active'
        with self.route('active') as run:
            self.execute(run);self.retain_fixture();self.finish(run)

    def test_stale_root_skill_and_plan_refuse_before_work(self):
        cases=[lambda:self.state.update(root=str(self.project)),lambda:self.state['_view'].update(stale=True),
            lambda:self.state['_view'].update(asof=(datetime.now(timezone.utc)-timedelta(seconds=40)).isoformat()),
            lambda:self.state['objects'][2].update(version=2),lambda:self.source.write_text('changed',encoding='utf-8'),
            lambda:self.plan.update(project_root=str(self.root))]
        original=deepcopy(self.state)
        for i,change in enumerate(cases):
            self.state.clear();self.state.update(deepcopy(original));self.source.write_text('Original checked source.',encoding='utf-8')
            self.plan['project_root']=str(self.project);change();self.write_plan()
            with self.subTest(i=i),self.assertRaises(ValueError):
                with self.route('refuse'+str(i)):self.calls.append('work')
        self.assertEqual(self.calls,[]);self.assertEqual(read_activity(self.root),[])

    def test_empty_tool_contract_and_invalid_categories_refuse_before_work(self):
        for i,change in enumerate([lambda:self.plan.update(tools=[]),lambda:self.plan['requirements'][0].update(category='unreviewed')]):
            self.plan['tools']=['test-output'];self.plan['requirements'][0]['category']='work';change();self.write_plan()
            with self.subTest(i=i),self.assertRaises(ValueError):
                with self.route('bad-contract'+str(i)):self.calls.append(1)
        self.assertEqual(self.calls,[]);self.assertEqual(read_activity(self.root),[])

    def test_acceptance_only_unchecked_and_duplicate_work_are_blocked(self):
        with self.route() as run:
            with self.assertRaises(ValueError):run.accept('accept','Fake acceptance',lambda:True)
            with self.assertRaises(ValueError):run.stage('check-output','Unchecked',lambda:self.calls.append(1))
            self.execute(run)
            with self.assertRaises(AlreadyRecorded):run.stage('check-output','Replay',lambda:self.calls.append(2),check=lambda _:True)
            self.retain_fixture();self.finish(run)
        self.assertEqual(self.calls,[])
        with self.assertRaises((AlreadyRecorded,ValueError)):
            with self.route():self.calls.append(3)
        self.assertEqual(self.calls,[])

    def test_missing_pending_foreign_receipt_and_unrelated_save_do_not_complete(self):
        with self.route() as run:
            self.execute(run);self.retain_fixture();original=deepcopy(self.receipt)
            for state in ['queued','running','uncertain','failed']:
                self.receipt['state']=state
                with self.subTest(state=state),self.assertRaises(RetentionPending):self.finish(run)
                self.assertEqual(read_activity(self.root)[0]['status'],'running')
            self.receipt.clear();self.receipt.update(deepcopy(original));self.receipt['id']='b'*32
            with self.assertRaises(ValueError):self.finish(run)
            self.receipt['id']='a'*32;self.receipt['action']='save'
            with self.assertRaises(ValueError):self.finish(run)
            self.receipt['action']='archive-research';self.finish(run)

    def test_final_evidence_cannot_weaken_requirements_change_sources_or_escape_paths(self):
        with self.route() as run:
            self.execute(run);self.retain_fixture();original=json.loads(self.evidence.read_text())
            mutations=[lambda e:e['requirements'][0].update(description='Always passes'),lambda e:e.update(uncertain_effect=True),
                lambda e:e['artifacts'][0].update(sha256='0'*64),lambda e:e['artifacts'][0].update(path=str(self.root/'unrelated')),
                lambda e:e.update(skills=['skill:other@1']),lambda e:e['requirements'][0].update(status='unknown'),
                lambda e:e.update(max_attempts=10),lambda e:e.update(timeout_seconds=86400)]
            for i,mutate in enumerate(mutations):
                value=deepcopy(original);mutate(value);self.evidence.write_text(json.dumps(value),encoding='utf-8')
                with self.subTest(i=i),self.assertRaises(ValueError):self.finish(run)
            self.evidence.write_text(json.dumps(original),encoding='utf-8');self.finish(run)

    def test_retention_content_links_source_chat_and_semantic_drift_are_rejected(self):
        with self.route() as run:
            self.execute(run);self.retain_fixture();original=deepcopy(self.state);saved=deepcopy(self.receipt)
            changes=[lambda:self.state['objects'][-1]['data'].update(content='Unrelated prose'),
                lambda:self.state['objects'][-1]['data'].update(status='candidate'),
                lambda:self.state['objects'][-1]['data']['capture']['provenance'].update(chat_id='foreign'),
                lambda:self.state['objects'][1]['data']['refs'].remove('memory:retained'),
                lambda:self.state['objects'][2]['data'].update(instructions='Different procedure'),
                lambda:self.state['objects'][2].update(version=3),
                lambda:self.state['memory_freshness']['retained'].update(current=False)]
            for i,change in enumerate(changes):
                self.state.clear();self.state.update(deepcopy(original));self.receipt.clear();self.receipt.update(deepcopy(saved));change()
                # Keep receipt/current memory equal to reach the content/provenance gate.
                self.receipt['result']['data']=deepcopy(self.state['objects'][-1]['data'])
                with self.subTest(i=i),self.assertRaises(ValueError):self.finish(run)
            self.state.clear();self.state.update(original);self.receipt.clear();self.receipt.update(saved);self.finish(run)

    def test_immutable_plan_and_second_checker_result_cannot_be_ignored(self):
        count=[]
        def checker(evidence):
            count.append(1)
            return evaluate_contract(evidence) if len(count)==1 else {'action':'review'}
        with self.route(checker=checker) as run:
            self.execute(run);self.retain_fixture()
            with self.assertRaisesRegex(ValueError,'after remote reads'):self.finish(run)
            run.checker=evaluate_contract;run.plan['outcome']='changed in memory'
            with self.assertRaisesRegex(ValueError,'in-memory'):self.finish(run)
            run.plan=deepcopy(self.plan);self.finish(run)

    def test_exact_retrieval_and_search_gate_are_repeatable(self):
        with self.route() as run:
            self.execute(run);self.retain_fixture()
            with patch.object(self.client,'knowledge',return_value={'record':None}),self.assertRaisesRegex(ValueError,'Exact-ID'):self.finish(run)
            with patch.object(self.client,'search',return_value={'records':[]}),self.assertRaisesRegex(ValueError,'discoverable'):self.finish(run)
            self.finish(run)

    def test_bound_accepted_recall_sources_checked_at_start_and_completion(self):
        source=dict(kind='memory',id='source',version=1,archived=False,data={'name':'Source','status':'accepted','content':'Scoped evidence.'})
        self.state['objects'].append(source);self.state['memory_freshness']['source']={'current':False}
        self.plan['source_bindings']={'memory:source':1};self.write_plan()
        with self.assertRaisesRegex(ValueError,'Bound recall'):
            with self.route():self.calls.append('work')
        self.assertEqual(read_activity(self.root),[])
        self.state['memory_freshness']['source']['current']=True
        with self.route() as run:
            self.execute(run);self.retain_fixture();source['version']=2
            with self.assertRaisesRegex(ValueError,'recall source drifted'):self.finish(run)
            source['version']=1;self.finish(run)

    def test_real_default_http_client_only_reads(self):
        owner=self;requests=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.command,self.path));value=owner.state if self.path=='/api/state' else owner.receipt
                body=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            self.client=PublishedClient('http://127.0.0.1:'+str(server.server_port))
            with self.route() as run:
                self.execute(run);self.retain_fixture();self.finish(run)
            self.assertEqual([method for method,_ in requests],['GET']*7)
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
