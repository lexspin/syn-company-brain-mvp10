import json,sys,tempfile,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from routine_engine import RoutineEngine,rows

class RoutineTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'runtime');self.root=Path(self.temp.name)
  (self.root/'routines').mkdir();(self.root/'data').mkdir()
  self.config={'machine_id':'local','timezone':'UTC','poll_seconds':300,'caps':{'daily_runs':2,'window_minutes':60,'window_runs':2},'routines':[
   {'id':'digest','name':'Briefing','machine':'local','kind':'morning-digest','schedule':'08:00','max_turns':0,'timeout_seconds':30,'output':'deliverables/briefs'}]}
  policy={'kind':'stack','id':'operating-policy','version':1,'archived':False,'data':{'schema_version':1,'requested_state':'idle','idle':{'max_batch':2,'cooldown_seconds':300}}}
  self.save();(self.root/'data/state.json').write_text(json.dumps({'runs':[],'objects':[policy]}))
  self.engine=RoutineEngine(self.root);self.now=datetime(2026,10,10,9,tzinfo=timezone.utc)
 def save(self):(self.root/'routines/registry.json').write_text(json.dumps(self.config))
 def tearDown(self):self.temp.cleanup()
 def tick(self):
  with patch('routine_engine.local_clock',side_effect=lambda d,z:d):return self.engine.tick(self.now)
 def test_occurrence_and_manual_identity_prevent_duplicate_run(self):
  self.tick();self.tick();self.assertEqual(len(self.engine.messages()),1)
  self.engine.request_run('digest','owner-request-001');self.now+=timedelta(seconds=300);self.tick();self.tick()
  self.assertEqual(len(self.engine.messages()),2)
  self.assertEqual(len([e for e in rows(self.engine.events) if e['status']=='started']),2)
 def test_log_caps_block_extra_calls(self):
  self.tick();self.engine.request_run('digest','owner-request-001');self.now+=timedelta(seconds=300);self.tick()
  self.engine.request_run('digest','owner-request-002');self.now+=timedelta(seconds=300);self.tick()
  self.assertEqual(len(self.engine.messages()),2)
  self.assertTrue(any(e['status']=='capped' for e in rows(self.engine.events)))
 def test_machine_scope_and_path_boundaries(self):
  self.config['machine_id']='other';self.save();self.tick();self.assertEqual(self.engine.messages(),[])
  self.config['routines'][0]['output']='../outside';self.save()
  with self.assertRaises(ValueError):self.engine.registry()
 def test_digest_keeps_missing_obligations_explicit(self):
  self.tick();self.assertIn('No verified task deadlines',self.engine.messages()[0]['text'])
  self.assertEqual(rows(self.engine.events)[-1]['cost'],0)

if __name__=='__main__':unittest.main()
