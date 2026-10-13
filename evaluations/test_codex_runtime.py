import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import codex_runtime as r
class RuntimeTests(unittest.TestCase):
 def test_completed_response(self):
  events=[{'type':'item.completed','item':{'type':'agent_message','text':'ok'}},{'type':'turn.completed'}]
  self.assertEqual(r.parse('\n'.join(map(json.dumps,events)),0)['text'],'ok')
 def test_partial_rejected(self):
  with self.assertRaises(RuntimeError):r.parse(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'partial'}}),0)
 def test_failed_rejected(self):
  with self.assertRaises(RuntimeError):r.parse('{"type":"turn.completed"}',1)
 def test_bad_input(self):
  for prompt in ['',None,'x'*100001]:
   with self.assertRaises(ValueError):r.run(prompt)
 @patch('codex_runtime.select_client',return_value={'path':'codex.exe','version':'codex-cli 0.162.0'})
 def test_argument_vector(self,_):
  cmd=r.command('gpt-6.1-sol');self.assertIn('read-only',cmd);self.assertEqual(cmd[-1],'-');self.assertIn('--ignore-user-config',cmd)
  self.assertIn('service_tier="default"',cmd);self.assertIn('features.fast_mode=false',cmd)
  self.assertIn('model_reasoning_effort="medium"',cmd);self.assertIn('--strict-config',cmd)
 @patch('codex_runtime.select_client',return_value={'path':'codex.exe','version':'codex-cli 0.162.0'})
 def test_requested_profiles_are_exact_and_standard(self,_):
  from model_profiles import PROFILES
  for profile,settings in PROFILES.items():
   cmd=r.command(model_profile=profile)
   self.assertEqual(cmd[cmd.index('--model')+1],settings['model'])
   self.assertIn('model_reasoning_effort='+json.dumps(settings['reasoning_effort']),cmd)
   self.assertIn('service_tier="default"',cmd)
   self.assertFalse(any('priority' in part or 'ultrafast' in part for part in cmd))
 def test_invalid_settings_never_start_process(self):
  with patch('codex_runtime.subprocess.Popen') as process:
   for settings in ({'model':'unknown'},{'model':'gpt-6-luna','reasoning_effort':'ultra'},
                    {'service_tier':'priority'},{'model_profile':'thinking','reasoning_effort':'ultra'},
                    {'reasoning_effort':'invented'},{'model_profile':'unknown'}):
    with self.assertRaises(ValueError):r.run('Reply once',**settings)
   process.assert_not_called()
 @patch('codex_runtime.select_client',return_value={'path':'codex.exe','version':'codex-cli 0.162.0'})
 @patch('codex_runtime.subprocess.Popen')
 def test_result_reports_requested_not_unproven_provider_settings(self,process,_):
  process.return_value.returncode=0
  process.return_value.communicate.return_value=('\n'.join(map(json.dumps,[{'type':'item.completed','item':{'type':'agent_message','text':'ok'}},{'type':'turn.completed'}])),'')
  result=r.run('Reply once',model_profile='innovation')
  self.assertEqual(result['execution']['model'],'gpt-6-astra')
  self.assertEqual(result['execution']['reasoning_effort'],'ultra')
  self.assertFalse(result['execution']['provider_settings_confirmed'])
  self.assertEqual(result['execution']['client_version'],'codex-cli 0.162.0')
 def test_nested_provider_model_error_is_actionable(self):
  message="The 'gpt-6-astra' model requires a newer version of Codex. Please upgrade."
  event={'type':'turn.failed','error':{'message':json.dumps({'error':{'message':message}})}}
  with self.assertRaisesRegex(RuntimeError,'gpt-6-astra.*newer Codex CLI'):r.parse(json.dumps(event),1)
  event={'type':'error','message':json.dumps({'error':{'message':"The 'gpt-6-luna' model is not supported when using Codex with a ChatGPT account."}})}
  with self.assertRaisesRegex(RuntimeError,'No different model was selected'):r.parse(json.dumps(event),1)
 def test_arbitrary_provider_payload_is_not_echoed(self):
  secret='Bearer secret-test-value sk-secret-example'
  with self.assertRaises(RuntimeError) as caught:r.parse(json.dumps({'type':'error','message':secret}),1)
  self.assertNotIn(secret,str(caught.exception))
  self.assertNotIn('sk-secret',str(caught.exception))
if __name__=='__main__':unittest.main()
