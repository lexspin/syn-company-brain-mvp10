import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from brain import Brain

class BrainTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'runtime')
  self.b=Brain(self.temp.name)
  self.b.save('skill','writer',{'name':'Writer','instructions':'Cite sources.'})
  self.b.save('agent','worker',{'name':'Worker','instructions':'Write','skills':['writer'],'tools':['index','retrieve','draft','validate','propose-memory']})
  self.b.save('agent','prompt-engineer',{'name':'Prompt engineer','instructions':'Refine the user request into a precise contract.','skills':['writer'],'tools':['draft']})
  self.b.save('memory','policy',{'name':'Reporting policy','content':'Use whole pounds.','source':'Owner decision','status':'accepted'})
  self.b.save('loop','report',{'name':'Report','max_attempts':2,'steps':[{'tool':'retrieve','agent':'worker','skill':'writer','instruction':'reporting policy'},{'tool':'draft','agent':'worker','skill':'writer','instruction':'Draft'},{'tool':'validate','agent':'worker','skill':'writer','instruction':'Check'}]})
 def tearDown(self):self.temp.cleanup()
 def test_native_pulse_keeps_executor_distinct_from_local_steps(self):
  data={'name':'Upkeep','instructions':'Inspect and preserve evidence.','steps':[],
        'execution':{'type':'codex-heartbeat','automation_id':'company-brain-mvp01-upkeep','schedule':'09:00 and 21:00','timezone':'Europe/London','status':'ACTIVE','verified_at':'2026-10-10'}}
  self.b.save('loop','upkeep',data)
  with self.assertRaisesRegex(ValueError,'native Codex'):self.b.snapshot('upkeep')
  with self.assertRaisesRegex(ValueError,'local step'):self.b.save('loop','bad-pulse',data|{'steps':[{'tool':'index','agent':'worker'}]})
  with self.assertRaises(ValueError):self.b.save('loop','bad-executor',data|{'execution':{'type':'shell'}})
 def start_without_thread(self):
  with patch('brain.threading.Thread'):return self.b.start('report','test-key-1234')
 def test_versions_and_stale_write(self):
  obj=self.b.get('memory','policy');self.b.save('memory','policy',obj['data']|{'content':'Use thousands.'},1)
  with self.assertRaises(ValueError):self.b.save('memory','policy',obj['data'],1)
  self.assertEqual(self.b.retrieve('policy')[0]['version'],2)
  self.assertTrue((Path(self.temp.name)/'records/memory/policy/v0001.json').exists())
 def test_explicit_memory_id_precedes_more_keyword_matches(self):
  self.b.save('memory','project-direction',{'name':'Owner direction','content':'Specific project facts','source':'Owner decision','status':'accepted'})
  result=self.b.retrieve('Cite memory:project-direction@v1 and use whole pounds reporting policy',limit=1)
  self.assertEqual(result[0]['id'],'project-direction')
 def test_common_words_do_not_retrieve_unrelated_evidence(self):
  self.assertEqual(self.b.retrieve('What did we do in the chat?'),[])
 def test_archive_and_candidate_exclusion(self):
  obj=self.b.get('memory','policy');self.b.save('memory','policy',obj['data'],1,True)
  self.assertEqual(self.b.retrieve('policy'),[])
  self.b.save('memory','candidate',{'name':'policy','content':'test','source':'hypothesis','status':'candidate'})
  self.assertEqual(self.b.retrieve('policy'),[])
 def test_parent_cycle(self):
  a=self.b.get('agent','worker')
  with self.assertRaises(ValueError):self.b.save('agent','worker',a['data']|{'parent':'worker'},1)
 def test_unavailable_capability(self):
  with self.assertRaises(ValueError):self.b.save('loop','bad',{'name':'Bad','steps':[{'tool':'email','agent':'worker'}]})
 def test_duplicate_delivery(self):
  first=self.start_without_thread();second=self.start_without_thread();self.assertEqual(first['id'],second['id'])
 def test_correction_invalidates_snapshot(self):
  snap=self.b.snapshot('report');obj=self.b.get('memory','policy');self.b.save('memory','policy',obj['data']|{'content':'Changed'},1)
  with self.assertRaises(ValueError):self.b.assert_fresh(snap)
 def test_restart_marks_interrupted(self):
  r=self.start_without_thread();reopened=Brain(self.temp.name);self.assertEqual(reopened.run(r['id'])['state'],'interrupted')
 def test_restore_from_export(self):
  dest=Path(self.temp.name)/'restore';dest.mkdir()
  import shutil
  shutil.copytree(Path(self.temp.name)/'records',dest/'records')
  restored=Brain(dest);self.assertEqual(restored.get('memory','policy')['data']['content'],'Use whole pounds.')
 def test_restore_rejects_export_identity_path_traversal(self):
  dest=Path(self.temp.name)/'malformed';folder=dest/'records/memory/policy';folder.mkdir(parents=True)
  data=self.b.get('memory','policy');data['id']='../../outside'
  (folder/'v0001.json').write_text(json.dumps(data),encoding='utf-8')
  with self.assertRaisesRegex(ValueError,'Invalid exported record'):Brain(dest)
  self.assertFalse((dest/'outside').exists())
 def test_complete_review_and_retention(self):
  r=self.start_without_thread()
  with patch('codex_runtime.run',return_value={'text':'Use whole pounds [policy@1].'}):self.b.execute(r['id'])
  self.assertEqual(self.b.run(r['id'])['state'],'needs_review')
  with self.assertRaises(ValueError):self.b.retain(r['id'])
  self.b.accept(r['id']);m=self.b.retain(r['id']);self.assertEqual(m['data']['status'],'accepted')
  self.assertEqual(self.b.retain(r['id'])['id'],m['id'])
 def test_artifact_tamper_blocks_acceptance(self):
  r=self.start_without_thread()
  with patch('codex_runtime.run',return_value={'text':'Use whole pounds [policy@1].'}):self.b.execute(r['id'])
  out=self.b.run(r['id'])['outputs'][0];(Path(self.temp.name)/out['path']).write_text('tampered')
  with self.assertRaises(ValueError):self.b.accept(r['id'])
 def test_historical_review_run_reports_changed_context_without_state_mutation(self):
  r=self.complete_run();self.assertTrue(r['context_current'])
  memory=self.b.get('memory','policy');self.b.save('memory','policy',memory['data']|{'content':'Use pennies.'},1)
  detailed=self.b.run(r['id']);summary=self.b.status()['runs'][0]
  for view in (detailed,summary):
   self.assertEqual(view['state'],'needs_review');self.assertFalse(view['context_current'])
   self.assertIn('memory:policy',view['context_note']);self.assertIn('create a new run',view['context_note'])
  self.assertNotIn('snapshot',summary)
  with self.assertRaisesRegex(ValueError,'changed'):self.b.accept(r['id'])
 def test_missing_citation_fails(self):
  r=self.start_without_thread()
  with patch('codex_runtime.run',return_value={'text':'Unsupported draft'}):self.b.execute(r['id'])
  self.assertEqual(self.b.run(r['id'])['state'],'failed')
 def test_graph_has_only_real_records(self):
  graph=self.b.graph();self.assertTrue(any(n['id']=='memory:policy' for n in graph['nodes']))
  self.assertFalse(any(n.get('area')=='business' for n in graph['nodes']))
  self.assertTrue(all(n['area'] in graph['areas'] for n in graph['nodes']))
  self.assertTrue(any(l['s']=='root' and l['k']=='tree' for l in graph['links']))
  self.assertTrue(any(l['t']=='memory:policy' and l['k']=='tree' for l in graph['links']))
 def test_chat_history_is_reused(self):
  with patch('codex_runtime.run',side_effect=[{'text':self.contract()},{'text':'Saved response'}]*2) as run:
   self.b.chat('test','Remember the reporting policy','worker');self.b.chat('test','What did we discuss?','worker')
   self.assertIn('Saved response',run.call_args.args[0])
   self.assertEqual(run.call_count,4)
 def test_backup_restores_runtime(self):
  import shutil,hashlib
  backup=Path(self.b.backup()['path'])
  manifest=json.loads((backup/'manifest.json').read_text())
  for name,sha in manifest.items():self.assertEqual(hashlib.sha256((backup/name).read_bytes()).hexdigest(),sha)
  restore=Path(self.temp.name)/'restored';(restore/'runtime').mkdir(parents=True)
  shutil.copy2(backup/'brain.sqlite',restore/'runtime/brain.sqlite')
  shutil.copytree(backup/'store',restore/'store')
  restored=Brain(restore);self.assertEqual(restored.get('memory','policy')['version'],1)
 def test_cancel_before_execution(self):
  r=self.start_without_thread();self.b.cancel(r['id']);self.b.execute(r['id'])
  self.assertEqual(self.b.run(r['id'])['state'],'cancelled')
 def test_resume_preserves_completed_steps(self):
  r=self.start_without_thread()
  with patch('codex_runtime.run',side_effect=RuntimeError('unavailable')):self.b.execute(r['id'])
  self.assertEqual(self.b.run(r['id'])['step'],1)
  reopened=Brain(self.temp.name)
  self.assertEqual(reopened.run(r['id'])['outputs'][0]['tool'],'retrieve')
  with patch('brain.threading.Thread'):reopened.resume(r['id'])
  with patch('codex_runtime.run',return_value={'text':'[policy@1]'}) as call:reopened.execute(r['id'])
  self.assertEqual(reopened.run(r['id'])['state'],'failed')
  call.assert_not_called()
 def complete_run(self):
  r=self.start_without_thread()
  with patch('codex_runtime.run',return_value={'text':'Use whole pounds [policy@1].'}):self.b.execute(r['id'])
  return self.b.run(r['id'])
 def test_retention_rechecks_artifact_integrity(self):
  r=self.complete_run();self.b.accept(r['id'])
  (Path(self.temp.name)/r['outputs'][0]['path']).write_text('changed after acceptance')
  with self.assertRaisesRegex(ValueError,'integrity'):self.b.retain(r['id'])
  with self.assertRaises(ValueError):self.b.get('memory','result-'+r['id'])
 def test_retention_links_source_versions(self):
  r=self.complete_run();self.b.accept(r['id']);memory=self.b.retain(r['id'])
  self.assertEqual(memory['data']['source_versions'],{'policy':1})
  self.assertIn('memory:policy',memory['data']['refs'])
 def test_source_correction_invalidates_transitive_derived_memory(self):
  r=self.complete_run();self.b.accept(r['id']);derived=self.b.retain(r['id'])
  self.b.save('memory','summary',{'name':'Reporting summary','content':'Use pounds for reporting.','source':'Accepted derived evidence','status':'accepted','source_versions':{derived['id']:1}})
  memory=self.b.get('memory','policy');self.b.save('memory','policy',memory['data']|{'content':'Use pennies.'},1)
  current={m['id'] for m in self.b.current_memories()}
  self.assertIn('policy',current);self.assertNotIn(derived['id'],current);self.assertNotIn('summary',current)
  self.assertFalse(self.b.status()['memory_freshness']['summary']['current'])
  self.assertFalse(any(m['id']=='summary' for m in self.b.snapshot('report')['memory']))
  with self.assertRaisesRegex(ValueError,'no longer current'):self.b.assert_records_fresh([derived])
 def test_source_archiving_invalidates_derived_memory(self):
  self.b.save('memory','summary',{'name':'Summary','content':'Use pounds.','source':'Reviewed result','status':'accepted','source_versions':{'policy':1}})
  memory=self.b.get('memory','policy');self.b.save('memory','policy',memory['data'],1,True)
  self.assertEqual(self.b.retrieve('pounds'),[])
 def test_resume_rejects_tampered_completed_artifact(self):
  r=self.start_without_thread()
  with patch('codex_runtime.run',side_effect=RuntimeError('offline')):self.b.execute(r['id'])
  output=self.b.run(r['id'])['outputs'][0]
  (Path(self.temp.name)/output['path']).write_text('tampered')
  with self.assertRaisesRegex(ValueError,'integrity'):self.b.resume(r['id'])
 def test_queued_loop_blocks_chat_and_backup(self):
  self.start_without_thread()
  with patch('codex_runtime.run') as call:
   with self.assertRaisesRegex(ValueError,'busy'):self.b.chat('pending','policy','worker')
   call.assert_not_called()
  with self.assertRaisesRegex(ValueError,'busy'):self.b.backup()
 def test_active_chat_blocks_loop_admission(self):
  self.b.acquire_interactive_worker()
  try:
   with self.assertRaisesRegex(ValueError,'busy'):self.start_without_thread()
   with self.b.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM runs').fetchone()[0],0)
  finally:self.b.active.release()
 def test_archived_skill_blocks_chat(self):
  skill=self.b.get('skill','writer');self.b.save('skill','writer',skill['data'],1,True)
  with patch('codex_runtime.run') as call:
   with self.assertRaisesRegex(ValueError,'archived skill'):self.b.chat('test','policy','worker')
   call.assert_not_called()
 def test_chat_does_not_publish_stale_context(self):
  def change_source(*args,**kwargs):
   memory=self.b.get('memory','policy');self.b.save('memory','policy',memory['data']|{'content':'Use pennies.'},1)
   return {'text':self.contract()}
  with patch('codex_runtime.run',side_effect=change_source):
   with self.assertRaisesRegex(ValueError,'changed'):self.b.chat('test','reporting policy','worker')
  with self.b.connect() as c:
   self.assertEqual(c.execute("SELECT count(*) FROM messages WHERE role='assistant'").fetchone()[0],0)
   self.assertEqual(c.execute("SELECT count(*) FROM messages WHERE role='error'").fetchone()[0],1)
 def test_correction_stops_retry_before_another_model_call(self):
  r=self.start_without_thread()
  def change_source(*args,**kwargs):
   memory=self.b.get('memory','policy');self.b.save('memory','policy',memory['data']|{'content':'Changed'},1)
   raise RuntimeError('Call failed after correction')
  with patch('codex_runtime.run',side_effect=change_source) as call:self.b.execute(r['id'])
  self.assertEqual(call.call_count,1)
  self.assertEqual(self.b.run(r['id'])['state'],'failed')
  self.assertEqual(len(self.b.run(r['id'])['attempts']),2)
 def test_cancellation_discards_model_output(self):
  r=self.start_without_thread()
  def cancel(*args,**kwargs):
   self.b.cancel(r['id']);return {'text':'[policy@1]'}
  with patch('codex_runtime.run',side_effect=cancel):self.b.execute(r['id'])
  result=self.b.run(r['id'])
  self.assertEqual(result['state'],'cancelled');self.assertEqual(result['step'],1)
  self.assertFalse(any(o['tool']=='draft' for o in result['outputs']))
 def test_citation_requires_exact_retrieved_identity(self):
  for text in ('Bare policy@1 text','Wrong [policy@10] citation','[policy@1] and invented [fiction@1]'):
   with self.subTest(text=text):
    with patch('brain.threading.Thread'):r=self.b.start('report','citation-'+str(abs(hash(text))))
    with patch('codex_runtime.run',return_value={'text':text}):self.b.execute(r['id'])
    self.assertEqual(self.b.run(r['id'])['state'],'failed')
 def test_completed_run_cannot_be_executed_again(self):
  r=self.complete_run();self.b.accept(r['id']);self.b.execute(r['id'])
  self.assertEqual(self.b.run(r['id'])['state'],'accepted')
 def test_schema_rejects_malformed_inputs(self):
  for kind,id,data in [('skill','bad',{'name':'Bad','instructions':[]}),('agent','bad',{'name':'Bad','instructions':'test','skills':'writer'}),('loop','bad',{'name':'Bad','steps':['invalid']}),('memory','bad',{'name':'Bad','status':'accepted','content':{},'source':'Owner'})]:
   with self.subTest(kind=kind):
    with self.assertRaises(ValueError):self.b.save(kind,id,data)
 def contract(self,agent='worker'):
  return json.dumps({'agent_id':agent,'task':'Explain the reporting policy','success_criteria':['Cite evidence'],'missing_information':[]})
 def test_hidden_prompt_engineer_routes_and_keeps_receipts(self):
  with patch('codex_runtime.run',side_effect=[{'text':self.contract()},{'text':'Use pounds [policy@1].'}]) as calls:
   result=self.b.chat('auto-test','Explain the reporting policy','coordinator')
  trace=result['trace'];self.assertEqual(calls.call_count,2)
  self.assertEqual(trace['selected_agent'],'worker');self.assertEqual(trace['state'],'completed')
  self.assertEqual([a['stage'] for a in trace['attempts']],['plan','answer'])
  self.assertEqual([a['agent_id'] for a in trace['attempts']],['prompt-engineer','worker'])
  self.assertTrue(all(a['state']=='completed' for a in trace['attempts']))
  with self.b.connect() as c:messages=[tuple(r) for r in c.execute('SELECT role,text FROM messages ORDER BY id')]
  self.assertEqual(messages,[('user','Explain the reporting policy'),('assistant','Use pounds [policy@1].')])
  reopened=Brain(self.temp.name)
  self.assertEqual(reopened.chat_turns('auto-test')[0]['id'],trace['id'])
  self.assertIn({'kind':'memory','id':'policy','version':1},trace['dependencies'])
 def test_invalid_planner_route_never_calls_specialist(self):
  with patch('codex_runtime.run',return_value={'text':self.contract('invented')}) as calls:
   with self.assertRaisesRegex(ValueError,'unavailable specialist'):self.b.chat('test','Help','coordinator')
  self.assertEqual(calls.call_count,1)
  trace=self.b.chat_turns('test')[0];self.assertEqual(trace['state'],'failed')
  self.assertEqual(len(trace['attempts']),1)
 def test_manual_specialist_cannot_be_overridden(self):
  with patch('codex_runtime.run',return_value={'text':self.contract('prompt-engineer')}) as calls:
   with self.assertRaisesRegex(ValueError,'unavailable specialist'):self.b.chat('test','Help','worker')
  self.assertEqual(calls.call_count,1)
 def test_invalid_contract_stops_after_one_call(self):
  with patch('codex_runtime.run',return_value={'text':'This is not JSON'}) as calls:
   with self.assertRaisesRegex(ValueError,'invalid JSON'):self.b.chat('test','Help','worker')
  self.assertEqual(calls.call_count,1)
 def test_specialist_failure_is_durable_and_not_retried(self):
  with patch('codex_runtime.run',side_effect=[{'text':self.contract()},RuntimeError('offline')]) as calls:
   with self.assertRaisesRegex(RuntimeError,'offline'):self.b.chat('test','Help','worker')
  trace=self.b.chat_turns('test')[0]
  self.assertEqual(calls.call_count,2);self.assertEqual(trace['state'],'failed')
  self.assertEqual(trace['attempts'][-1]['state'],'failed')
 def test_evidence_budget_preserves_prioritized_source_identity(self):
  memory=self.b.get('memory','policy');memory['data']['content']='evidence '*4000
  supplied=json.loads(self.b.evidence_context([memory],1000))
  self.assertEqual(supplied[0]['id'],'policy');self.assertTrue(supplied[0]['truncated'])
 def test_evidence_preserves_verification_limitations(self):
  memory=self.b.get('memory','policy');memory['data']['validation']={'scope':'Instruction change only; no performance result.'}
  supplied=json.loads(self.b.evidence_context([memory]))
  self.assertEqual(supplied[0]['validation'],memory['data']['validation'])
 def test_selected_specialist_receives_current_role_and_skill_sources(self):
  self.b.save('memory','handbook',{'name':'Technical handbook','content':'GROUNDING SENTINEL: observable outputs.','source':'Reviewed handbook','status':'accepted','evidence_type':'Technical reference excerpt'})
  self.b.save('memory','journal',{'name':'Journal','content':'JOURNAL SENTINEL: bounded examples.','source':'Reviewed journal','status':'accepted'})
  agent=self.b.get('agent','worker');self.b.save('agent','worker',agent['data']|{'refs':['memory:handbook']},1)
  skill=self.b.get('skill','writer');self.b.save('skill','writer',skill['data']|{'refs':['memory:journal']},1)
  with patch('codex_runtime.run',side_effect=[{'text':self.contract()},{'text':'Answer'}]) as calls:self.b.chat('role-source','Help with this task','worker')
  actual_request=calls.call_args.args[0]
  self.assertIn('GROUNDING SENTINEL',actual_request);self.assertIn('JOURNAL SENTINEL',actual_request)
  self.assertIn('Technical reference excerpt',actual_request)
  source=actual_request.split('Accepted evidence:\n',1)[1].split('\nOriginal request:',1)[0]
  evidence=json.loads(source);self.assertEqual(evidence[0]['id'],'policy')
  self.assertTrue(any(r['id']=='handbook' and r['version']==1 for r in evidence))
 def test_role_linked_sources_exclude_stale_candidate_and_archived_memory(self):
  self.b.save('memory','stale',{'name':'Outdated handbook','content':'STALE SOURCE','source':'Older derivation','status':'accepted','source_versions':{'policy':1}})
  self.b.save('memory','candidate',{'name':'Proposed source','content':'CANDIDATE SOURCE','source':'Proposal','status':'candidate'})
  self.b.save('memory','archived',{'name':'Archived source','content':'ARCHIVED SOURCE','source':'Historical source','status':'accepted'},archived=True)
  agent=self.b.get('agent','worker');agent=self.b.save('agent','worker',agent['data']|{'refs':['memory:stale','memory:candidate','memory:archived']},1)
  memory=self.b.get('memory','policy');self.b.save('memory','policy',memory['data']|{'content':'Use pennies.'},1)
  evidence=self.b.chat_evidence('Unknown subject',agent,self.b.chat_skills(agent))
  self.assertEqual(evidence,[])
 def test_explicit_memory_precedes_bounded_role_sources(self):
  refs=[]
  for i in range(4):
   id='reference-'+str(i);refs.append('memory:'+id)
   self.b.save('memory',id,{'name':'Handbook','content':'Instructional material','source':'Reference','status':'accepted'})
  agent=self.b.get('agent','worker');agent=self.b.save('agent','worker',agent['data']|{'refs':refs},1)
  evidence=self.b.chat_evidence('Use memory:policy',agent,self.b.chat_skills(agent))
  self.assertEqual([r['id'] for r in evidence],['policy','reference-0','reference-1','reference-2'])
 def test_project_directory_must_exist_and_be_absolute(self):
  project=self.b.save('project','work',{'name':'Work','path':str(Path(self.temp.name)),'scope':'Bounded project','refs':['memory:policy']})
  self.assertEqual(project['data']['scope'],'Bounded project')
  for path in ('relative/path',str(Path(self.temp.name)/'does-not-exist')):
   with self.assertRaises(ValueError):self.b.save('project','invalid',{'name':'Invalid','path':path})
  self.assertFalse((Path(self.temp.name)/'does-not-exist').exists())
  self.assertTrue(any(n['id']=='project:work' and n['kind']=='project' for n in self.b.graph()['nodes']))
 def test_project_scope_and_linked_evidence_reach_selected_specialist(self):
  self.b.save('memory','project-note',{'name':'Project brief','content':'PROJECT SOURCE SENTINEL','source':'Owner project brief','status':'accepted'})
  self.b.save('project','work',{'name':'Workshop','path':str(Path(self.temp.name)),'scope':'WORKSHOP SCOPE','refs':['memory:project-note']})
  with patch('codex_runtime.run',side_effect=[{'text':self.contract()},{'text':'Answer'}]) as calls:
   result=self.b.chat('project-conversation','Help with next task','worker',project_id='work')
  actual=calls.call_args.args[0];self.assertIn('WORKSHOP SCOPE',actual);self.assertIn('PROJECT SOURCE SENTINEL',actual)
  self.assertIn({'kind':'project','id':'work','version':1},result['trace']['dependencies'])
if __name__=='__main__':unittest.main()
