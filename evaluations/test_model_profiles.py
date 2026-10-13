import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from brain import Brain
from model_profiles import resolve,automatic_eligible,PROFILES

class ProfileTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'runtime');self.b=Brain(self.tmp.name)
  self.b.save('skill','writing',{'name':'Writing','instructions':'Write precisely.'})
  self.b.save('agent','worker',{'name':'Worker','instructions':'Write','skills':['writing'],'tools':['draft'],'model_profile':'routine'})
  self.b.save('agent','innovator',{'name':'Innovation Director','instructions':'Compare hypotheses','skills':['writing'],'tools':['draft'],'model_profile':'innovation'})
  self.b.save('agent','prompt-engineer',{'name':'Prompt engineer','instructions':'Route a request','skills':[],'tools':['draft'],'model_profile':'light'})
 def tearDown(self):self.tmp.cleanup()
 def contract(self,id):return {'text':json.dumps({'agent_id':id,'task':'Write','success_criteria':[],'missing_information':[]})}
 def test_auto_does_not_offer_ultra_on_routine_or_negated_request(self):
  for prompt in ('Summarize known evidence','Use creativity in the routine edit','No innovation: summarize the source','Summarize this innovation paper'):
   with patch('codex_runtime.run',side_effect=[self.contract('worker'),{'text':'done'}]) as call:
    self.b.chat('routing',prompt,'auto')
   self.assertNotIn('Innovation Director',call.call_args_list[0].args[0])
 def test_explicit_innovation_and_manual_role_selection_allow_ultra(self):
  for prompt,id in [('Develop an innovation plan','auto'),('Compare options','innovator')]:
   with patch('codex_runtime.run',side_effect=[self.contract('innovator'),{'text':'done'}]) as call:
    result=self.b.chat('innovation',prompt,id)
   self.assertEqual(call.call_args_list[0].kwargs['model'],'gpt-6-luna')
   self.assertEqual(call.call_args_list[0].kwargs['reasoning_effort'],'low')
   self.assertEqual(call.call_args_list[1].kwargs['model'],'gpt-6-astra')
   self.assertEqual(call.call_args_list[1].kwargs['reasoning_effort'],'ultra')
   self.assertEqual(call.call_args_list[1].kwargs['service_tier'],'default')
   self.assertEqual(result['trace']['execution'][1]['reasoning_effort'],'ultra')
 def test_planner_cannot_smuggle_ultra_outside_available_registry(self):
  with patch('codex_runtime.run',return_value=self.contract('innovator')) as call:
   with self.assertRaises(ValueError):self.b.chat('denied','Routine summary','auto')
  self.assertEqual(call.call_count,1)
 def test_draft_step_propagates_snapshot_profile(self):
  self.b.save('loop','draft',{'name':'Draft','steps':[{'tool':'draft','agent':'innovator','skill':'writing','instruction':'Compare hypotheses'}]})
  snap=self.b.snapshot('draft')
  with patch('codex_runtime.run',return_value={'text':'Candidate'}) as call:
   self.b.step(snap['loop']['data']['steps'][0],snap,[],lambda:False)
  self.assertEqual(call.call_args.kwargs['model_profile'],'innovation')
  self.assertEqual(call.call_args.kwargs['reasoning_effort'],'ultra')
 def test_invalid_profile_rejected_on_save(self):
  original=self.b.get('agent','worker')
  with self.assertRaises(ValueError):self.b.save('agent','worker',original['data']|{'model':'gpt-6-astra'},original['version'])
 def test_effort_is_validated_even_for_custom_profile(self):
  self.assertEqual(resolve('gpt-6-astra','high')['model_profile'],'custom')
  with self.assertRaises(ValueError):resolve('gpt-6-luna','ultra')
  self.assertFalse(automatic_eligible({'model':'gpt-6.1-sol','reasoning_effort':'ultra'},'Summarize a paper'))
 def test_contractions_and_never_do_not_enable_ultra(self):
  for prompt in ("Don't innovate; summarize facts.","Don't use Astra Ultra.","Don’t innovate today.","Never innovate for this edit.","Never select Ultra."):
   with self.subTest(prompt=prompt):self.assertFalse(automatic_eligible({'model_profile':'innovation'},prompt))

if __name__=='__main__':unittest.main()
