import sys,json
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'app'),str(root/'evaluations')]
import test_brain
from archive_research import capture_source
from improvements import propose,apply
f=test_brain.BrainTests();f.setUp();b=f.b;checks=[]
def record(step,detail,status='PASS'):checks.append({'step':step,'status':status,'detail':detail})
try:
 b.save('project','simulation',{'name':'Isolated simulation','path':f.temp.name,'scope':'Synthetic fixture only','refs':[]})
 record('Intake','Synthetic article/transcript fixture: reporting policy. No source fetched, watched or transcribed.')
 sources=b.retrieve('reporting policy');assert sources[0]['id']=='policy';record('Recall','Current policy@1 retrieved.')
 a=b.get('agent','worker');b.save('agent','worker',a['data']|{'tools':a['data']['tools']+['review']},a['version'])
 loop=b.get('loop','report');d=loop['data'];d['steps'].append({'tool':'review','agent':'worker','skill':'writer','instruction':'Check claims.'});d['completion']='save-reviewed-candidate';b.save('loop','report',d,loop['version'])
 run=f.start_without_thread();assert f.start_without_thread()['id']==run['id'];record('Routing and handoff','Exact loop/worker/skill/source snapshot; duplicate start reuses run.')
 review={'decision':'pass','summary':'The reporting unit is supported.','claims':[{'claim':'Use whole pounds.','status':'supported','source':'policy@1','quote':'Use whole pounds.'}]}
 with patch('codex_runtime.run',side_effect=[{'text':'Use whole pounds [policy@1].'},{'text':json.dumps(review)}]):b.execute(run['id'])
 completed=b.run(run['id']);assert completed['state']=='completed';assert len(completed['outputs'])==4
 record('Execute and review','Real local runner, persisted artifacts and quote validation; model outputs are simulated.')
 candidate=b.get('memory','candidate-'+run['id']);assert candidate['data']['status']=='candidate';assert candidate['id'] not in [m['id'] for m in b.current_memories()]
 record('Candidate memory','Reviewed draft saved exactly once; excluded from accepted retrieval.')
 args={'title':'Simulation lesson','content':'A fabricated source quote must fail validation. Retain source identities and check literal quotations. Synthetic fixture only.','provenance':{'chat_id':'isolated-simulation'},'request_key':'simulation-lesson-001','project_id':'simulation','skill_ids':['writer']}
 lesson=capture_source(b,**args);assert capture_source(b,**args)['id']==lesson['id'];assert 'memory:'+lesson['id'] in b.get('project','simulation')['data']['refs'];assert 'memory:'+lesson['id'] in b.get('skill','writer')['data']['refs']
 record('Archive, links and retrieval','Lesson capture deduplicates and adds reciprocal project/skill links in the isolated store.')
 with patch('codex_runtime.run',return_value={'text':'Cite source IDs and preserve uncertainty. Check literal quotes before submission.'}):proposal=propose(b,'writer','Preserve uncertainty and check literal quotes.')
 old=b.get('skill','writer')['version'];assert proposal['data']['status']=='candidate';apply(b,proposal['id']);assert b.get('skill','writer')['version']==old+1
 record('Skill learning','Proposal remains candidate until explicit fixture approval; applying creates a new version and preserves predecessor. This is not automatic promotion.')
 native={'name':'Native fixture','instructions':'Read and archive fixture evidence.','execution':{'type':'codex-chat','trigger':'research-request','skill_id':'writer'},'refs':['skill:writer']};b.save('loop','native',native)
 req={'name':'Manual fixture','type':'native-work-request','status':'candidate','content':'Synthetic research request','source':'Simulation','request_state':'queued','loop_id':'native','loop_version':1,'refs':['loop:native']}
 b.save('memory','request',req);claim=req|{'request_state':'running','claimant':'simulation','claimed_at':'2026-10-10T22:00:00Z'};b.save('memory','request',claim,1)
 try:b.save('memory','request',claim,1)
 except ValueError:pass
 else:raise AssertionError('Competing claim accepted')
 linked=b.get('memory',lesson['id']);b.save('memory',lesson['id'],linked['data']|{'refs':linked['data']['refs']+['loop:native']},linked['version'])
 b.save('memory','request',claim|{'request_state':'completed','result_ref':lesson['id'],'completion_evidence':'Synthetic artifact and backlink assertions passed.','completed_at':'2026-10-10T22:01:00Z'},2)
 record('Manual queue lifecycle','Queued → version-bound claim → result-linked completion; competing claim rejected.')
 # Negative probes: record gaps, never mutate production or pretend expected safety passed.
 b.save('memory','skip-claim',req)
 try:b.save('memory','skip-claim',req|{'request_state':'completed','result_ref':'policy','completion_evidence':'Unchecked assertion','completed_at':'2026-10-10T22:01:00Z'},1)
 except ValueError:record('Completion without claim','Rejected.')
 else:record('Completion without claim','Backend accepts queued → completed with an unrelated existing memory and unverified evidence text. Native skill instructions, not backend transition enforcement, currently prevent this.','GAP')
 b.save('memory','stale-request',req)
 b.save('loop','native',native|{'instructions':'Changed procedure'},1)
 try:b.save('memory','stale-request',req|{'request_state':'running','claimant':'simulation','claimed_at':'2026-10-10T22:00:00Z'},1)
 except ValueError:record('Stale native workflow claim','Rejected.')
 else:record('Stale native workflow claim','Backend accepts a claim bound to old loop version; dispatcher skill must perform freshness check.','GAP')
 record('Scheduled invocation','This simulation does not invoke a real scheduler. Nonempty scheduled execution requires a separate actual run receipt.','LIMIT')
 record('External tools and media','YouTube acquisition, paid generation and provider semantic quality are not exercised by fixture simulations.','LIMIT')
finally:
 f.tearDown()
 out=root/'runtime/all-steps-simulation.json';out.write_text(json.dumps({'isolated':True,'checks':checks},indent=2),encoding='utf-8');print(json.dumps({'report':str(out),'checks':checks},indent=2))
