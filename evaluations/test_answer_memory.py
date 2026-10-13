import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from brain import Brain
from answer_memory import recall_known,retain_answer,normalize_query
from commands import CommandQueue,CommandWorker

class AnswerMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'runtime');self.root=Path(self.temp.name);self.b=Brain(self.root)
        self.b.save('skill','writer',{'name':'Writer','instructions':'Use current sources.'})
        self.b.save('agent','worker',{'name':'Worker','instructions':'Write an evidence-bound answer.','skills':['writer'],'tools':['draft']})
        self.b.save('agent','other',{'name':'Other','instructions':'Other role scope.','skills':[],'tools':['draft']})
        self.b.save('agent','prompt-engineer',{'name':'Engineer','instructions':'Refine the request.','skills':[],'tools':['draft']})
        self.b.save('memory','policy',{'name':'Reporting policy','content':'Report whole pounds.','source':'Owner decision','status':'accepted'})
        self.b.save('project','lab',{'name':'Lab','path':str(self.root),'scope':'Reporting product','refs':['memory:policy','skill:writer']})
        self.b.save('project','other-lab',{'name':'Other Lab','path':str(self.root),'scope':'Separate project','refs':[]})
        self.query='What is the reporting policy for Report42?'
        self.answer='Report whole pounds for Report42 [policy@1].'
        self.queue=CommandQueue(self.root);self.worker=CommandWorker(self.b,self.queue,Mock())
    def tearDown(self):self.worker.stop();self.temp.cleanup()
    def completed(self,query=None,answer=None,missing=None):
        plan={'agent_id':'worker','task':query or self.query,'success_criteria':['Cite the reporting policy.'],'missing_information':missing or []}
        with patch('codex_runtime.run',side_effect=[{'text':json.dumps(plan)},{'text':answer if answer is not None else self.answer}]):
            return self.b.chat('main',query or self.query,'worker',project_id='lab')
    def saved(self):
        result=self.completed();extra=retain_answer(self.b,result);self.assertIn('memory_saved',extra);return result|extra
    def test_real_l2_retention_then_l1_replay_has_zero_calls_and_durable_truthful_trace(self):
        first=self.saved();saved=self.b.get('memory',first['memory_saved']['id'])
        self.assertEqual(saved['data']['source_versions'],{'policy':1});self.assertEqual(saved['data']['content'],self.answer)
        self.assertIn('not independently verified',saved['data']['evidence_type'])
        for kind,id in [('project','lab'),('skill','writer')]:self.assertIn('memory:'+saved['id'],self.b.get(kind,id)['data']['refs'])
        with patch('codex_runtime.run') as run:second=self.b.chat('main',self.query,'worker',project_id='lab')
        run.assert_not_called();self.assertEqual(second['text'],self.answer);self.assertEqual(second['mode'],'l1_reuse');self.assertEqual(second['model_calls'],0)
        trace=self.b.chat_turn(second['turn_id']);self.assertEqual(trace['attempts'][0]['stage'],'l1-reuse');self.assertEqual(trace['execution'],[])
        self.assertEqual(trace['discovery'][0]['reused_from']['id'],saved['id']);self.assertEqual(trace['discovery'][0]['tool_calls'],0)
        self.assertEqual(retain_answer(self.b,second),{});self.assertEqual(len([m for m in self.b.list('memory') if m['data'].get('type')=='l2-answer-cache']),1)
        with patch('codex_runtime.run') as run:third=self.b.chat('main','  '+self.query+'  ','worker',project_id='lab')
        run.assert_not_called();self.assertEqual(third['mode'],'l1_reuse')
    def test_changed_source_or_configuration_or_project_never_replays(self):
        self.saved();project=self.b.get('project','lab')
        self.assertIsNone(recall_known(self.b,'main',self.query,'worker',self.b.get('project','other-lab')))
        self.assertIsNone(recall_known(self.b,'main',self.query,'other',project))
        self.assertIsNone(recall_known(self.b,'main',self.query.replace('42','43'),'worker',project))
        current=self.b.get('skill','writer');self.b.save('skill','writer',current['data']|{'instructions':'New answer method.'},current['version'])
        self.assertIsNone(recall_known(self.b,'main',self.query,'worker',project))
        current=self.b.get('memory','policy');self.b.save('memory','policy',current['data']|{'content':'Report pennies.'},current['version'])
        self.assertIsNone(recall_known(self.b,'main',self.query,'worker',project))
    def test_changed_conversation_context_prevents_wrong_reuse(self):
        self.saved()
        with self.b.connect() as c:c.execute('INSERT INTO messages(session,role,text,created) VALUES(?,?,?,?)',('main','user','For the following response, use a German explanation.','9999'))
        self.assertIsNone(recall_known(self.b,'main',self.query,'worker',self.b.get('project','lab')))
    def test_uncited_unresolved_and_unknown_citations_are_not_retained(self):
        for answer,missing in [('No sources supplied.',[]),('A citation [unknown@1].',[]),('Policy [policy@1] and malformed [unknown@v1].',[]),(self.answer,['Missing decision from owner'])]:
            result=self.completed(answer=answer,missing=missing)
            self.assertIn('retention_skipped',retain_answer(self.b,result))
        self.assertEqual(len([m for m in self.b.list('memory') if m['data'].get('type')=='l2-answer-cache']),0)
    def test_retention_failure_keeps_completed_answer_and_does_not_retry_model(self):
        plan={'agent_id':'worker','task':self.query,'success_criteria':['Use source'],'missing_information':[]}
        with patch('codex_runtime.run',side_effect=[{'text':json.dumps(plan)},{'text':self.answer}]) as run,patch('answer_memory.retain_answer',side_effect=OSError('test retention unavailable')):
            result=self.worker.dispatch('chat',{'session':'main','prompt':self.query,'agent':'worker','project_id':'lab'},'a'*32)
        self.assertEqual(run.call_count,2);self.assertEqual(result['text'],self.answer);self.assertIn('retention_warning',result);self.assertEqual(self.b.chat_turn(result['turn_id'])['state'],'completed')
    def test_retention_runs_after_active_lock_release_and_is_idempotent(self):
        plan={'agent_id':'worker','task':self.query,'success_criteria':['Use source'],'missing_information':[]}
        def retain(brain,result):
            self.assertFalse(brain.active.locked());return retain_answer(brain,result)
        with patch('codex_runtime.run',side_effect=[{'text':json.dumps(plan)},{'text':self.answer}]),patch('answer_memory.retain_answer',side_effect=retain):
            result=self.worker.dispatch('chat',{'session':'main','prompt':self.query,'agent':'worker','project_id':'lab'},'b'*32)
        original=self.b.get('memory',result['memory_saved']['id']);again=retain_answer(self.b,result)
        self.assertEqual(again['memory_saved']['id'],original['id']);self.assertEqual(again['memory_saved']['version'],original['version'])
    def test_exact_source_lookup_is_current_and_makes_no_model_call(self):
        with patch('codex_runtime.run') as run:result=self.b.chat('main','memory:policy','worker',project_id='lab')
        run.assert_not_called();self.assertEqual(result['mode'],'l1_lookup');self.assertIn('[policy@1]',result['text']);self.assertEqual(retain_answer(self.b,result),{})
        current=self.b.get('memory','policy');self.b.save('memory','policy',current['data'],current['version'],True)
        self.assertIsNone(recall_known(self.b,'main','memory:policy','worker',self.b.get('project','lab')))
    def test_normalization_preserves_identifiers_numbers_and_code_layout(self):
        self.assertEqual(normalize_query('  Report42  policy? '),'Report42 policy?')
        self.assertNotEqual(normalize_query('Report42'),normalize_query('report42'))
        self.assertNotEqual(normalize_query('Report42'),normalize_query('Report43'))
        self.assertNotEqual(normalize_query('`a  b`'),normalize_query('`a b`'))
    def test_relative_time_questions_do_not_become_timeless_cached_answers(self):
        result=self.completed(query='Which policy applies today?')
        self.assertIn('Relative-time',retain_answer(self.b,result)['retention_skipped'])
        self.assertFalse(any(m['data'].get('type')=='l2-answer-cache' for m in self.b.list('memory')))
    def test_explicit_archive_queue_reuses_retained_answer_and_links_without_duplicate(self):
        result=self.saved();memory_id=result['memory_saved']['id']
        self.b.save('skill','reviewer',{'name':'Reviewer','instructions':'Review source support.'})
        payload={'turn_id':result['turn_id'],'project_id':'lab','skill_ids':['reviewer']}
        request_id=self.queue.enqueue('archive-research',payload)
        with patch('check_map.rebuild'),patch('check_map.check',return_value={'ok':True}):self.worker.run_once()
        receipt=self.queue.receipt(request_id)
        self.assertTrue(receipt['ok']);self.assertEqual(receipt['result']['id'],memory_id)
        self.assertEqual(receipt['result']['capture_status'],'linked')
        self.assertIn('memory:'+memory_id,self.b.get('skill','reviewer')['data']['refs'])
        self.assertFalse(any(m['id']=='research-'+result['turn_id'] for m in self.b.list('memory')))
        before=self.b.get('memory',memory_id)
        repeated=self.queue.enqueue('archive-research',payload)
        with patch('check_map.rebuild'),patch('check_map.check',return_value={'ok':True}):self.worker.run_once()
        self.assertEqual(self.queue.receipt(repeated)['result']['version'],before['version'])
        with patch('codex_runtime.run') as run:reused=self.b.chat('main',self.query,'worker',project_id='lab')
        run.assert_not_called();self.assertEqual(reused['mode'],'l1_reuse')
    def test_retention_preserves_prior_explicit_capture_home(self):
        from archive_research import capture
        result=self.completed();archived=capture(self.b,result['turn_id'])
        saved=retain_answer(self.b,result)
        self.assertEqual(saved['memory_saved']['id'],archived['id'])
        self.assertFalse(any(m['id']=='answer-'+result['turn_id'] for m in self.b.list('memory')))

if __name__=='__main__':unittest.main()
