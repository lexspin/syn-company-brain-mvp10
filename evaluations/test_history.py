import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from history_intake import import_history,atomic_projection
from history_recall import search,verify,final_output

class HistoryTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'runtime')
  self.root=Path(self.temp.name);self.home=self.root/'codex';(self.home/'sessions').mkdir(parents=True)
 def tearDown(self):self.temp.cleanup()
 def write(self,id,source,messages,title='Research thesis'):
  path=self.home/'sessions'/(id+'.jsonl')
  rows=[{'type':'session_meta','payload':{'id':id,'thread_source':source,'source':'vscode','cwd':'C:/Projects/Thesis','timestamp':'2026-10-01T10:00:00Z'}}]
  rows+=messages
  path.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
  with (self.home/'session_index.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'id':id,'thread_name':title})+'\n')
  return path
 def message(self,text,id='msg-1',role='user',phase=None,timestamp='2026-10-01T11:00:00Z'):
  payload={'type':'message','id':id,'role':role,'content':[{'type':'input_text' if role=='user' else 'output_text','text':text}]}
  if phase:payload['phase']=phase
  return {'timestamp':timestamp,'type':'response_item','payload':payload}
 def test_import_keeps_only_root_human_text_and_exact_final_output_pointer(self):
  source=self.write('root-session-0001','user',[self.message('<environment_context>injected path</environment_context>'),self.message('My thesis requires source-backed conclusions.','owner'),self.message('PRIVATE REASONING','reason','assistant','analysis'),self.message('A final artifact link.','answer','assistant','final_answer'),self.message('Change that conclusion, keep the evidence.','correction')])
  self.write('subagent-session-0001','subagent',[self.message('AGENT GENERATED REQUEST')])
  self.write('guardian-session-0001','guardian_review',[self.message('GUARDIAN REQUEST')])
  coverage=import_history(self.root,self.home)
  self.assertEqual(coverage['retained_messages'],2);self.assertEqual(coverage['retained_output_references'],1)
  history_files=list((self.root/'store/history/messages').glob('*.json'))
  texts='\n'.join(p.read_text() for p in history_files)
  self.assertNotIn('PRIVATE REASONING',texts);self.assertNotIn('AGENT GENERATED',texts);self.assertNotIn('injected path',texts)
  result=search(self.root,'thesis conclusion',domain='thesis-writing');self.assertTrue(result)
  self.assertEqual(result[0]['source_file'],str(source.resolve()));self.assertTrue(verify(self.root,result))
  correction=next(json.loads(p.read_text()) for p in history_files if 'Change that conclusion' in p.read_text())
  output=final_output(self.root,correction['previous_output_id'])
  self.assertEqual(output['text'],'A final artifact link.')
  self.assertTrue(output['prompt_ids']);self.assertIn('Not inferred',output['acceptance'])
 def test_idempotent_rescan_does_not_rewrite_message_records(self):
  self.write('root-session-0001','user',[self.message('Always cite my thesis sources.')])
  first=import_history(self.root,self.home);path=next((self.root/'store/history/messages').glob('*.json'));before=path.read_bytes();modified=path.stat().st_mtime_ns
  second=import_history(self.root,self.home)
  self.assertEqual(first['retained_messages'],second['retained_messages']);self.assertEqual(path.read_bytes(),before);self.assertEqual(path.stat().st_mtime_ns,modified)
  self.assertEqual(second['scan']['unchanged_sessions'],1)
 def test_injected_goal_plugin_context_and_programmatic_sessions_are_excluded(self):
  self.write('root-session-0001','user',[self.message('<codex_internal_context source="goal">Keep running this generated goal</codex_internal_context>','goal'),self.message('<recommended_plugins>Generated plugin catalog</recommended_plugins>','plugins'),self.message('<in-app-browser-context>Browser data</in-app-browser-context>\n## My request:\nUse this real prompt.','real')])
  automated=self.write('legacy-programmatic',None,[self.message('Execute this Company Brain generated task capsule.')])
  lines=automated.read_text().splitlines();meta=json.loads(lines[0]);meta['payload']['originator']='company_brain_local';lines[0]=json.dumps(meta);automated.write_text('\n'.join(lines)+'\n')
  coverage=import_history(self.root,self.home)
  self.assertEqual(coverage['retained_messages'],1)
  self.assertEqual(coverage['excluded_sessions']['programmatic_company_brain_execution'],1)
  self.assertEqual(search(self.root,'real prompt')[0]['excerpt'],'Use this real prompt.')
 def test_domains_keep_lore_and_linkedin_voice_context_separate(self):
  self.write('root-session-lore','user',[self.message('For Silicone Twins lore use an intimate narrative.','lore')],title='Silicone Twins lore')
  self.write('root-session-blog','user',[self.message('For LinkedIn use a concise professional narrative.','blog')],title='LinkedIn blog')
  import_history(self.root,self.home)
  lore=search(self.root,'narrative',domain='lore');blog=search(self.root,'narrative',domain='linkedin-blog')
  self.assertEqual(len(lore),1);self.assertEqual(lore[0]['thread_id'],'root-session-lore')
  self.assertEqual(len(blog),1);self.assertEqual(blog[0]['thread_id'],'root-session-blog')
 def test_obvious_credentials_are_redacted_and_historical_instruction_is_not_activated(self):
  self.write('root-session-0001','user',[self.message('Always remember token sk-'+('A'*40))])
  import_history(self.root,self.home);record=json.loads(next((self.root/'store/history/messages').glob('*.json')).read_text())
  self.assertNotIn('sk-'+('A'*40),record['text']);self.assertEqual(record['credential_redactions'],1)
  self.assertTrue(record['classification']['instruction_signal']);self.assertEqual(record['classification']['status'],'historical-context-candidate')
 def test_changed_immutable_record_is_rejected(self):
  self.write('root-session-0001','user',[self.message('Thesis evidence')]);import_history(self.root,self.home)
  result=search(self.root,'thesis');path=self.root/result[0]['record_path'];path.write_text('changed')
  with self.assertRaisesRegex(ValueError,'changed'):verify(self.root,result)
 def test_projection_replace_retries_transient_onedrive_sharing_lock(self):
  import os
  path=self.root/'projection.json';path.write_text('{"old":true}')
  real_replace=os.replace;calls=[]
  def replace(source,target):
   calls.append(1)
   if len(calls)<3:raise PermissionError('Temporary OneDrive sharing lock')
   return real_replace(source,target)
  with patch('history_intake.os.replace',side_effect=replace),patch('history_intake.time.sleep'):
   atomic_projection(path,{'new':True})
  self.assertEqual(json.loads(path.read_text()),{'new':True});self.assertEqual(len(calls),3)

if __name__=='__main__':unittest.main()
