import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from brain import Brain
from routing_context import cards,relevant_connections

class RoutingTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=ROOT/'runtime');self.b=Brain(self.temp.name)
  self.b.save('skill','writing',{'name':'Writing','purpose':'Prepare prose','instructions':'EXACT SELECTED SKILL PROCEDURE'})
  self.b.save('agent','worker',{'name':'Writer','purpose':'Prepare prose','instructions':'EXACT SELECTED ROLE PROCEDURE','skills':['writing'],'tools':['draft']})
  self.b.save('agent','other',{'name':'Other','purpose':'Financial summaries','instructions':'UNRELATED LONG PROCEDURE','skills':[],'tools':['draft']})
  self.b.save('agent','prompt-engineer',{'name':'Prompt engineer','instructions':'Make a task contract','skills':[],'tools':['draft']})
 def tearDown(self):self.temp.cleanup()
 def test_compact_cards_exclude_procedure_bodies(self):
  encoded=json.dumps(cards(self.b,self.b.list('agent')))
  self.assertNotIn('EXACT SELECTED',encoded);self.assertNotIn('UNRELATED LONG',encoded)
  self.assertIn('Prepare prose',encoded);self.assertIn('writing',encoded)
 def test_plan_then_exact_selected_context_and_tool_scope(self):
  contract={'agent_id':'worker','task':'Write a summary','success_criteria':[],'missing_information':[]}
  with patch('codex_runtime.run',side_effect=[{'text':json.dumps(contract)},{'text':'Draft'}]) as call:
   result=self.b.chat('test','Write a summary','coordinator')
  planner=call.call_args_list[0].args[0];answer=call.call_args_list[1].args[0]
  self.assertNotIn('EXACT SELECTED',planner);self.assertNotIn('UNRELATED LONG',planner)
  self.assertIn('EXACT SELECTED ROLE',answer);self.assertIn('EXACT SELECTED SKILL',answer)
  self.assertNotIn('UNRELATED LONG',answer)
  self.assertIsNone(call.call_args_list[0].kwargs['memory_context'])
  self.assertEqual(call.call_args_list[1].kwargs['memory_context'],[{'kind':'skill','id':'writing','version':1}])
  self.assertEqual(result['trace']['discovery'][0]['layer'],'L1')
 def test_external_catalog_is_relevant_and_never_promoted_to_v2(self):
  folder=Path(self.temp.name)/'docs';folder.mkdir()
  (folder/'CONNECTION-CATALOG.json').write_text(json.dumps({'connections':[
   {'id':'linkedin','tool_names':['linkedin_search_people'],'status':'available-in-codex-host','v2_execution':'not-connected-to-cli'},
   {'id':'hotline','tool_names':['hotline_search'],'status':'available-in-codex-host'},
   {'id':'video','tool_names':['video_generate'],'status':'unreachable'}]}))
  result=relevant_connections(self.temp.name,'LinkedIn people research')
  self.assertEqual([r['id'] for r in result],['linkedin'])
  self.assertEqual(result[0]['v2_execution'],'not-connected-to-cli')
  self.assertNotIn('hotline',json.dumps(relevant_connections(self.temp.name,'search')))

if __name__=='__main__':unittest.main()
