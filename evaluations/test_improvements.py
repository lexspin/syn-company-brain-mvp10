import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from brain import Brain
from improvements import propose,apply

class ImprovementTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'runtime')
  self.b=Brain(self.temp.name)
  self.b.save('skill','writer',{'name':'Writer','instructions':'Cite sources.'})
 def tearDown(self):self.temp.cleanup()
 def proposal(self):
  with patch('codex_runtime.run',return_value={'text':'Cite sources. Preserve uncertainty. Example: missing evidence stays unknown.'}):
   return propose(self.b,'writer','Keep uncertainty visible.')
 def test_proposal_does_not_activate_and_apply_preserves_history(self):
  p=self.proposal()
  self.assertEqual(self.b.get('skill','writer')['version'],1)
  self.assertEqual(self.b.retrieve('uncertainty'),[])
  result=apply(self.b,p['id']);self.assertEqual(result['data']['applied_version'],2)
  self.assertEqual(apply(self.b,p['id'])['version'],result['version'])
  self.assertTrue((Path(self.temp.name)/'records/skill/writer/v0001.json').exists())
 def test_changed_skill_rejects_old_proposal(self):
  p=self.proposal();skill=self.b.get('skill','writer')
  self.b.save('skill','writer',skill['data']|{'instructions':'New procedure'},1)
  with self.assertRaisesRegex(ValueError,'changed'):apply(self.b,p['id'])
 def test_failed_generation_does_not_leave_worker_locked(self):
  with patch('codex_runtime.run',side_effect=RuntimeError('unavailable')):
   with self.assertRaises(RuntimeError):propose(self.b,'writer','Keep uncertainty visible.')
  self.assertFalse(self.b.active.locked())
  self.assertEqual(self.b.list('memory'),[])
 def test_improvement_uses_routine_profile(self):
  with patch('codex_runtime.run',return_value={'text':'Cite available evidence only.'}) as call:
   propose(self.b,'writer','Keep uncertainty visible.')
  self.assertEqual(call.call_args.kwargs['model_profile'],'routine')

if __name__=='__main__':unittest.main()
