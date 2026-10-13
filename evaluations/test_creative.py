import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from brain import Brain
from commands import validate, CommandQueue, CommandWorker
import creative

def board():
 return {'schema':1,'title':'Continuity test','brief':'One actor enters the same room.','ratio':'16:9','width':1920,'height':1080,'style':'natural','notes':'',
 'cast':[{'id':'actor-a','name':'Actor A','description':'Blue coat','image':'https://example.com/actor.jpg'}],
 'places':[{'id':'room-a','name':'Room A','description':'Window camera left','image':'https://example.com/room.jpg'}],
 'shots':[{'id':'shot-a','title':'Entrance','direction':'Actor walks in and sits.','frame':'Wide','lens':'35 mm','motion':'Slow track','cut':'Match on action','duration':5,'cast':['actor-a'],'place':'room-a','image':'','video':'','motion_reference':'','audio':'','last_image':'','sketch':[[[0,0],[.5,.5]]],'notes':'No wardrobe change','trim_in':0,'trim_out':5,'accepted':False}]}

class CreativeTests(unittest.TestCase):
 def cue_board(self):
  b=board();b['cues']=[{'id':'cue-a','name':'Room','kind':'ambience','shot':'shot-a','offset':1,'duration':3,'actor':'','place':'room-a','text':'','prompt':'Quiet room','preset':'room','url':'','source_in':0,'gain':.2,'pan':0,'fade_in':.1,'fade_out':.2,'muted':False,'license':'Original procedural sound','source':'Local recipe'}];return b
 def test_cues_persist_with_actor_and_place_links(self):
  b=self.cue_board();b['cues'][0]['actor']='actor-a'
  r=creative.save_board(self.brain,{'id':'board-cue','version':0,'board':b})
  self.assertEqual(r['data']['board']['cues'],b['cues'])
 def test_cue_rejects_dangling_shot_actor_place(self):
  for f in ('shot','actor','place'):
   b=self.cue_board();b['cues'][0][f]='missing'
   with self.assertRaises(ValueError):creative.validate_board(b,self.root)
 def test_cue_timing_fades_and_nonfinite_are_rejected(self):
  for f,v in [('offset',5),('duration',5),('fade_in',4),('gain',float('nan')),('pan',float('inf')),('source_in',-1)]:
   b=self.cue_board();b['cues'][0][f]=v
   with self.assertRaises(ValueError):creative.validate_board(b,self.root)
 def test_cue_preset_matches_lane_and_url_is_safe(self):
  for f,v in [('preset','fade-black'),('url','http://localhost/sound.wav'),('muted','false')]:
   b=self.cue_board();b['cues'][0][f]=v
   with self.assertRaises(ValueError):creative.validate_board(b,self.root)
 def test_cue_follows_shot_order_but_cannot_extend_past_end(self):
  b=self.cue_board();second=copy.deepcopy(b['shots'][0]);second['id']='shot-b';b['shots'].append(second)
  b['cues'][0]['duration']=7;creative.validate_board(b,self.root)
  b['shots'].reverse()
  with self.assertRaises(ValueError):creative.validate_board(b,self.root)
 def test_old_boards_without_cues_remain_valid(self):
  self.assertEqual(creative.validate_board(board(),self.root)['schema'],1)
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'runtime');self.root=Path(self.temp.name);self.brain=Brain(self.root)
  self.brain.save('project','company-brain',{'name':'Test','path':str(self.root),'scope':'Test only'})
  self.brain.save('skill','video-production-orchestrator',{'name':'Video','instructions':'Keep continuity.'})
  self.board=board()
 def tearDown(self):self.temp.cleanup()
 def save(self):return creative.save_board(self.brain,{'id':'board-test','version':0,'board':self.board})
 def test_references_reach_provider_payload_in_stable_order(self):
  p=creative.compile_shot(self.board,'shot-a','video',self.root)
  self.assertEqual(p['image_urls'],['https://example.com/actor.jpg','https://example.com/room.jpg']);self.assertIn('@Image1: Actor A',p['prompt']);self.assertIn('@Image2: Room A',p['prompt']);self.assertEqual(p['provider'],'bytedance')
 def test_still_edit_preserves_all_references(self):
  p=creative.compile_shot(self.board,'shot-a','still',self.root)
  self.assertEqual(p['model'],'bytedance/seedream-v4-edit');self.assertEqual(len(p['image_urls']),2);self.assertEqual(p['image_size'],{'width':1920,'height':1080})
 def test_text_still_does_not_claim_reference_edit(self):
  self.board['shots'][0].update(cast=[],place='')
  p=creative.compile_shot(self.board,'shot-a','still',self.root);self.assertEqual(p['model'],'bytedance/seedream-v4-text-to-image');self.assertNotIn('image_urls',p)
 def test_missing_identity_reference_blocks_generation(self):
  self.board['cast'][0]['image']=''
  with self.assertRaisesRegex(ValueError,'Actor A'):creative.compile_shot(self.board,'shot-a','video',self.root)
 def test_first_last_never_drops_identity_references(self):
  self.board['shots'][0]['last_image']='https://example.com/last.jpg'
  with self.assertRaisesRegex(ValueError,'exactly one'):creative.compile_shot(self.board,'shot-a','video',self.root)
 def test_first_last_maps_explicitly(self):
  self.board['shots'][0].update(cast=[],place='',image='https://example.com/first.jpg',last_image='https://example.com/last.jpg')
  p=creative.compile_shot(self.board,'shot-a','video',self.root);self.assertEqual(p['image_url'],'https://example.com/first.jpg');self.assertNotIn('image_urls',p)
 def test_selected_output_is_not_silently_motion_reference(self):
  self.board['shots'][0]['video']='https://example.com/selected.mp4'
  self.assertNotIn('video_urls',creative.compile_shot(self.board,'shot-a','video',self.root))
 def test_board_versions_and_reciprocal_links(self):
  r=self.save();self.assertEqual(r['version'],1)
  for k,i in [('project','company-brain'),('skill','video-production-orchestrator')]:self.assertIn('memory:board-test',self.brain.get(k,i)['data']['refs'])
  with self.assertRaises(ValueError):self.save()
 def test_no_generation_without_explicit_authority(self):
  self.save()
  with patch('creative.provider_call') as call:
   with self.assertRaises(ValueError):creative.submit(self.brain,{'id':'board-test','version':1,'shot_id':'shot-a','media':'video','paid_authorized':False},'a'*32)
   call.assert_not_called()
 def test_stale_board_cannot_spend(self):
  self.save()
  with patch('creative.provider_call') as call:
   with self.assertRaises(ValueError):creative.submit(self.brain,{'id':'board-test','version':0,'shot_id':'shot-a','media':'video','paid_authorized':True},'a'*32)
   call.assert_not_called()
 def test_uncertain_submission_is_never_repeated(self):
  self.save();p={'id':'board-test','version':1,'shot_id':'shot-a','media':'video','paid_authorized':True}
  with patch('creative.key',return_value='secret'),patch('creative.provider_call',side_effect=RuntimeError('uncertain')) as call:
   with self.assertRaises(RuntimeError):creative.submit(self.brain,p,'a'*32)
   result=creative.submit(self.brain,p,'a'*32);self.assertEqual(result['state'],'uncertain');self.assertEqual(call.call_count,1)
   self.assertNotIn('secret',creative.job_path(self.root,'a'*32).read_text())
 def test_poll_only_uses_saved_provider_identity(self):
  self.save();p={'id':'board-test','version':1,'shot_id':'shot-a','media':'video','paid_authorized':True}
  with patch('creative.key',return_value='secret'),patch('creative.provider_call',return_value={'id':'saved-id','status':'queued'}):creative.submit(self.brain,p,'b'*32)
  with patch('creative.provider_call',return_value={'id':'saved-id','status':'completed','video':{'url':'https://example.com/out.mp4'}}) as call:
   self.assertEqual(creative.poll(self.root,'b'*32)['state'],'completed');call.assert_called_once_with('/v2/video/generations?generation_id=saved-id')
 def test_transport_rejects_arbitrary_generation_fields(self):
  with self.assertRaises(ValueError):validate('creative-generate',{'id':'board-test','version':1,'shot_id':'shot-a','media':'video','paid_authorized':True,'endpoint':'https://evil.com'})
 def test_board_rejects_invalid_links_sketch_and_trim(self):
  for field,value in [('cast',['missing']),('sketch',[[[2,0]]]),('trim_out',99),('duration',0)]:
   b=board();b['shots'][0][field]=value
   with self.assertRaises(ValueError):creative.validate_board(b,self.root)
 def test_assets_reject_traversal_svg_and_fake_image(self):
  for name in ['../outside.png','x.png','a'*64+'.svg']:
   with self.assertRaises(ValueError):creative.asset_path(self.root,name)
  for data in ['data:image/svg+xml;base64,PHN2Zz4=','data:image/png;base64,YWJj']:
   with self.assertRaises(ValueError):creative.import_image(self.root,data)
 def test_media_rejects_active_and_private_links(self):
  for url in ['javascript:alert(1)','http://example.com/a','https://127.0.0.1/a','https://user:password@example.com/a','https://localhost/a']:
   with self.assertRaises(ValueError):creative.public_url(url)

if __name__=='__main__':unittest.main()
