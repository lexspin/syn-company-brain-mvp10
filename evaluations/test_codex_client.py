import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
import codex_client as client

class ClientTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'runtime');root=Path(self.tmp.name)
  self.old=root/'old.exe';self.new=root/'new.exe'
  self.old.write_bytes(b'old');self.new.write_bytes(b'new')
 def tearDown(self):self.tmp.cleanup()
 def info(self,path,version,model):
  return {'path':str(path),'version':version,'version_key':client.version_key(version),'models':{model:{'low','medium','ultra'}}}
 def test_compatible_existing_app_client_beats_older_path_entry(self):
  def probe(path,*_):return self.info(path,'0.147.0' if path==str(self.old) else '0.162.0-alpha.17.2','gpt-5.6-sol' if path==str(self.old) else 'gpt-6.1-sol')
  with patch('codex_client.candidate_paths',return_value=[self.old,self.new]),patch('codex_client._probe',side_effect=probe):
   chosen=client.select_client('gpt-6.1-sol','medium')
  self.assertEqual(chosen['path'],str(self.new));self.assertEqual(chosen['version'],'0.162.0-alpha.17.2')
 def test_unknown_requested_model_does_not_fall_back(self):
  with patch('codex_client.candidate_paths',return_value=[self.old]),patch('codex_client._probe',return_value=self.info(self.old,'0.147.0','gpt-5.6-sol')):
   with self.assertRaisesRegex(RuntimeError,'no different model was selected'):client.select_client('gpt-6.1-sol','medium')
 def test_override_is_authoritative_and_must_be_compatible(self):
  with patch.dict(os.environ,{'CODEX_BIN':str(self.old)}),patch('codex_client._probe',return_value=self.info(self.old,'0.147.0','gpt-5.6-sol')):
   self.assertEqual(client.candidate_paths(),[self.old.resolve()])
   with self.assertRaisesRegex(RuntimeError,'CODEX_BIN does not advertise'):client.select_client('gpt-6-astra','medium')
 def test_relative_override_rejected(self):
  with patch.dict(os.environ,{'CODEX_BIN':'codex.exe'}):
   with self.assertRaisesRegex(RuntimeError,'absolute'):client.candidate_paths()
 def test_same_release_prefers_stable_and_numeric_versions(self):
  self.assertGreater(client.version_key('0.162.0'),client.version_key('0.162.0-alpha.17.2'))
  self.assertGreater(client.version_key('0.162.0-alpha.17.2'),client.version_key('0.147.0'))
 def test_bundled_probe_never_refreshes_account_catalog(self):
  from types import SimpleNamespace
  client._probe.cache_clear()
  outputs=[SimpleNamespace(returncode=0,stdout='codex-cli 0.162.0'),SimpleNamespace(returncode=0,stdout='{"models":[{"slug":"gpt-6-luna","supported_reasoning_levels":[{"effort":"low"}]}]}')]
  with patch('codex_client.subprocess.run',side_effect=outputs) as run:
   info=client._probe(str(self.new),1,1)
  self.assertEqual(run.call_args_list[1].args[0],[str(self.new),'debug','models','--bundled'])
  self.assertEqual(info['models']['gpt-6-luna'],{'low'})

if __name__=='__main__':unittest.main()
