"""Creative boards and AIMLAPI jobs. Called only by the owning command worker.

Boards use Brain's versioned ledger. Media and provider receipts are private.
No paid request is retried automatically, including ambiguous timeouts.
"""
import base64
import hashlib
import ipaddress
import json
import math
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urlencode
from commands import atomic_json, stamp

MODELS = {'still':'bytedance/seedream-v4-text-to-image',
          'edit':'bytedance/seedream-v4-edit', 'video':'bytedance/seedance-2-0'}
RATIOS = ['16:9','9:16','1:1','4:3','3:4','21:9']
PRESETS = [
 {'id':'establish','name':'Establish the world','frame':'Wide','lens':'24 mm','motion':'Slow lateral track; ease in and out; hold the final composition.','cut':'Cut on a clear subject action.','purpose':'Show geography before moving closer.'},
 {'id':'intimate','name':'Move closer to a feeling','frame':'Close-up','lens':'85 mm','motion':'Very slow dolly in; keep eyes sharp; no zoom reset.','cut':'Hold the reaction before cutting.','purpose':'A quiet emotional beat with a stable eyeline.'},
 {'id':'follow','name':'Follow the action','frame':'Medium','lens':'35 mm','motion':'Track beside the subject at matching speed; preserve screen direction.','cut':'Match the action into the next angle.','purpose':'Readable movement through the same environment.'},
 {'id':'reveal','name':'Reveal something important','frame':'Wide','lens':'35 mm','motion':'Dolly past a foreground occluder to reveal the subject; settle gently.','cut':'Cut after the reveal has registered.','purpose':'Let camera movement reveal story information.'},
 {'id':'dialogue','name':'Conversation coverage','frame':'Over the shoulder','lens':'50 mm','motion':'Locked camera; restrained natural performance; preserve the 180-degree line.','cut':'J-cut the next line; preserve original voice.','purpose':'Consistent actors, eyelines and room geography.'},
 {'id':'detail','name':'Detail that connects the cut','frame':'Insert','lens':'100 mm macro','motion':'Locked close detail; one deliberate physical action.','cut':'Match shape, motion or sound to the next shot.','purpose':'An object or gesture bridges two larger shots.'},
 {'id':'orbit','name':'Orbit a still subject','frame':'Medium','lens':'50 mm','motion':'Slow 30-degree orbit at constant radius; settle without accelerating.','cut':'Cut on the final stable composition.','purpose':'Reveal depth without an uncontrolled spin.'},
 {'id':'portrait','name':'Portrait with room to move','frame':'Full figure','lens':'35 mm','motion':'Track gently while keeping all required subjects inside the portrait frame.','cut':'Preserve movement and headroom across the cut.','purpose':'Vertical delivery with intentional blocking.'},
]
STYLES = {
 'natural':'Natural cinematic light, restrained contrast, believable textures, coherent colour temperature.',
 'noir':'Low-key motivated light, deep shadow, controlled highlights, restrained monochrome palette.',
 'dream':'Soft atmospheric depth, delicate halation, coherent pastel palette, physically readable movement.',
 'editorial':'Clean directional light, deliberate negative space, tactile surfaces, restrained editorial colour.',
 'scifi':'Motivated practical light, believable materials, subtle volumetric atmosphere, coherent futuristic design.',
 'sketch':'Loose graphite storyboard lines, clear silhouettes, simple light and shadow, readable composition.',
}

def key():
    return os.environ.get('AIMLAPI_API_KEY') or os.environ.get('AIMLAPI_KEY') or ''

def public_url(value):
    if not isinstance(value,str): raise ValueError('Media link must be text.')
    p=urlsplit(value)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):
        raise ValueError('Use a public HTTPS media link.')
    if p.hostname.lower() in ('localhost','localhost.localdomain') or p.hostname.endswith(('.local','.internal')):
        raise ValueError('Local media must be imported into the board.')
    try:
        if not ipaddress.ip_address(p.hostname).is_global: raise ValueError('Private network media links are not supported.')
    except ValueError as error:
        if str(error)=='Private network media links are not supported.': raise
    return value

def asset_path(root, name):
    if not isinstance(name,str) or not re.fullmatch(r'[a-f0-9]{64}\.(png|jpg|webp)',name):
        raise ValueError('Invalid image identity.')
    path=Path(root)/'runtime/creative/assets'/name
    if not path.resolve().is_relative_to((Path(root)/'runtime/creative/assets').resolve()): raise ValueError('Invalid image location.')
    return path

def import_image(root, encoded):
    if not isinstance(encoded,str) or len(encoded)>175000: raise ValueError('Use a smaller board preview image (under 125 KB). Originals stay in their source project.')
    match=re.fullmatch(r'data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)',encoded)
    if not match: raise ValueError('Import a PNG, JPEG or WebP image.')
    raw=base64.b64decode(match[2],validate=True)
    mime=match[1]
    valid=(mime=='png' and raw.startswith(b'\x89PNG\r\n\x1a\n') or mime=='jpeg' and raw.startswith(b'\xff\xd8\xff') or mime=='webp' and raw[:4]==b'RIFF' and raw[8:12]==b'WEBP')
    if not valid or len(raw)>128000: raise ValueError('Invalid or oversized image.')
    name=hashlib.sha256(raw).hexdigest()+('.jpg' if mime=='jpeg' else '.'+mime)
    path=asset_path(root,name);path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists(): path.write_bytes(raw)
    return {'asset':name,'url':'/creative/assets/'+name,'bytes':len(raw)}

def text(value,label,limit=8000):
    if not isinstance(value,str) or len(value)>limit: raise ValueError(label+' is too long or is not text.')
    return value

def media(value,root):
    if not value: return ''
    if value.startswith('/creative/assets/'):
        path=asset_path(root,value.rsplit('/',1)[-1])
        if not path.is_file(): raise ValueError('A referenced image is missing.')
        return value
    return public_url(value)

def validate_board(board,root):
    if not isinstance(board,dict) or board.get('schema')!=1: raise ValueError('Unsupported creative board.')
    allowed={'schema','title','brief','ratio','width','height','style','cast','places','shots','notes','cues'}
    if board.keys()-allowed: raise ValueError('Unknown board fields.')
    for field in ('title','brief','style','notes'): text(board.get(field,''),field)
    if not board.get('title','').strip(): raise ValueError('Give the production a name.')
    if board.get('ratio') not in RATIOS: raise ValueError('Choose a supported aspect ratio.')
    for f in ('width','height'):
        if type(board.get(f)) is not int or not 256<=board[f]<=4096: raise ValueError('Canvas dimensions must be 256–4096 pixels.')
    identities=set()
    for kind in ('cast','places'):
        rows=board.get(kind,[])
        if not isinstance(rows,list) or len(rows)>30: raise ValueError('Use up to 30 '+kind+' references.')
        for item in rows:
            if not isinstance(item,dict) or set(item)-{'id','name','description','image'}: raise ValueError('Invalid continuity reference.')
            if not re.fullmatch(r'[a-z0-9-]{1,50}',item.get('id','')) or item['id'] in identities: raise ValueError('Each reference needs a unique identity.')
            identities.add(item['id'])
            for f in ('name','description'): text(item.get(f,''),f)
            media(item.get('image',''),root)
    shots=board.get('shots',[])
    if not isinstance(shots,list) or len(shots)>40: raise ValueError('Use up to 40 shots per board.')
    shotids=set()
    for shot in shots:
        allowed={'id','title','direction','frame','lens','motion','cut','duration','cast','place','image','video','motion_reference','audio','last_image','sketch','notes','trim_in','trim_out','accepted'}
        if not isinstance(shot,dict) or shot.keys()-allowed: raise ValueError('Invalid shot fields.')
        if not re.fullmatch(r'[a-z0-9-]{1,50}',shot.get('id','')) or shot['id'] in shotids: raise ValueError('Each shot needs a unique identity.')
        shotids.add(shot['id'])
        for f in ('title','direction','frame','lens','motion','cut','notes'): text(shot.get(f,''),f)
        if type(shot.get('duration')) is not int or not 4<=shot['duration']<=15: raise ValueError('Seedance 2.0 shots must be 4–15 seconds.')
        if not isinstance(shot.get('cast',[]),list) or len(shot.get('cast',[]))>8 or any(x not in {v['id'] for v in board.get('cast',[])} for x in shot.get('cast',[])): raise ValueError('Shot actor link is missing.')
        if shot.get('place') and shot['place'] not in {v['id'] for v in board.get('places',[])}: raise ValueError('Shot location link is missing.')
        for f in ('image','last_image'): media(shot.get(f,''),root)
        for f in ('video','motion_reference','audio'):
            if shot.get(f): public_url(shot[f])
        sketch=shot.get('sketch',[])
        if not isinstance(sketch,list) or len(sketch)>150: raise ValueError('Sketch has too many strokes.')
        for stroke in sketch:
            if not isinstance(stroke,list) or len(stroke)>500: raise ValueError('Sketch stroke is too long.')
            for point in stroke:
                if not isinstance(point,list) or len(point)!=2 or any(type(v) not in (float,int) or not 0<=v<=1 for v in point): raise ValueError('Invalid sketch coordinates.')
        start,end=shot.get('trim_in',0),shot.get('trim_out',shot['duration'])
        if any(type(v) not in (int,float) for v in (start,end)) or not 0<=start<end<=shot['duration']: raise ValueError('Keep the trim inside the shot duration.')
        if type(shot.get('accepted',False)) is not bool: raise ValueError('Invalid shot approval.')
    validate_cues(board)
    if len(json.dumps(board))>110000: raise ValueError('This board is full. Start a new sequence.')
    return board

def validate_cues(board):
    cues=board.get('cues',[])
    if not isinstance(cues,list) or len(cues)>100: raise ValueError('Use up to 100 timeline cues.')
    ids=set();shots={s['id']:s for s in board['shots']}
    actors={a['id'] for a in board.get('cast',[])};places={a['id'] for a in board.get('places',[])}
    length=sum(s['trim_out']-s['trim_in'] for s in board['shots'])
    for cue in cues:
        fields={'id','name','kind','shot','offset','duration','actor','place','text','prompt','preset','url','source_in','gain','pan','fade_in','fade_out','muted','license','source'}
        if not isinstance(cue,dict) or cue.keys()-fields: raise ValueError('Invalid timeline cue fields.')
        if not re.fullmatch(r'[a-z0-9-]{1,50}',cue.get('id','')) or cue['id'] in ids: raise ValueError('Each cue needs a unique identity.')
        ids.add(cue['id'])
        if cue.get('kind') not in ('dialogue','ambience','effect','music','visual'): raise ValueError('Choose a timeline layer.')
        if cue.get('shot') not in shots: raise ValueError('Link each cue to an existing shot.')
        for field in ('name','actor','place','text','prompt','url','license','source'): text(cue.get(field,''),field,4000)
        if cue.get('actor') and cue['actor'] not in actors: raise ValueError('Cue actor link is missing.')
        if cue.get('place') and cue['place'] not in places: raise ValueError('Cue place link is missing.')
        presets={'placeholder','room','wind','rain','whoosh','impact','pulse','fade-black','warm','cool'}
        if cue.get('preset') not in presets: raise ValueError('Unknown cue preset.')
        valid={'dialogue':{'placeholder'},'ambience':{'placeholder','room','wind','rain'},'effect':{'placeholder','whoosh','impact'},'music':{'placeholder','pulse'},'visual':{'placeholder','fade-black','warm','cool'}}
        if cue['preset'] not in valid[cue['kind']]: raise ValueError('Preset does not belong to this layer.')
        for field,low,high in [('offset',0,600),('duration',.1,600),('source_in',0,3600),('gain',0,1),('pan',-1,1),('fade_in',0,30),('fade_out',0,30)]:
            n=cue.get(field)
            if type(n) not in (int,float) or not math.isfinite(n) or not low<=n<=high: raise ValueError('Invalid cue '+field+'.')
        before=0
        for shot in board['shots']:
            if shot['id']==cue['shot']: break
            before+=shot['trim_out']-shot['trim_in']
        if cue['offset']>=shots[cue['shot']]['trim_out']-shots[cue['shot']]['trim_in']: raise ValueError('Cue must begin inside its linked shot.')
        if before+cue['offset']+cue['duration']>length+.001: raise ValueError('Cue extends beyond the sequence. Shorten it or add a shot.')
        if cue['fade_in']+cue['fade_out']>cue['duration']: raise ValueError('Cue fades must fit its duration.')
        if type(cue.get('muted')) is not bool: raise ValueError('Invalid cue mute state.')
        if cue.get('url'): public_url(cue['url'])

def save_board(brain,p):
    board=validate_board(p['board'],brain.root)
    if p['version']:
        existing=brain.get('memory',p['id'])
        if existing['data'].get('record_type')!='creative-board': raise ValueError('This record is not a creative board.')
    project=p.get('project_id','company-brain')
    brain.get('project',project)
    refs=['project:'+project]
    for ident in ('video-production-orchestrator','art-direction','editing-direction','shorts-format-video','voicelab-delivery'):
        try: brain.get('skill',ident);refs.append('skill:'+ident)
        except (KeyError,ValueError): pass
    data={'name':board['title'],'status':'accepted','source':'Owner creative board; saved from the local creative workspace. Working direction, not an approved finished film.',
          'content':board['brief']+'\n\n'+'\n'.join(s['id']+': '+s['title']+' — '+s['direction'] for s in board['shots']) or 'Creative production board.',
          'record_type':'creative-board','board':board,'refs':refs}
    result=brain.save('memory',p['id'],data,p['version'])
    warnings=[]
    for ref in refs:
        kind,ident=ref.split(':',1);record=brain.get(kind,ident)
        if 'memory:'+p['id'] not in record['data'].get('refs',[]):
            try: brain.save(kind,ident,record['data']|{'refs':[*record['data'].get('refs',[]),'memory:'+p['id']]},record['version'])
            except Exception: warnings.append(ref)
    return result|({'link_warning':'Board saved; backlink update needs review: '+', '.join(warnings)} if warnings else {})

def compile_shot(board,shot_id,kind,root):
    validate_board(board,root)
    shot=next((s for s in board['shots'] if s['id']==shot_id),None)
    if not shot: raise ValueError('Choose a saved shot.')
    if kind not in ('still','video'): raise ValueError('Choose still or video.')
    if not shot['direction'].strip(): raise ValueError('Describe what happens in this shot first.')
    refs=[];lines=[]
    for item in [x for x in board['cast'] if x['id'] in shot.get('cast',[])]+[x for x in board['places'] if x['id']==shot.get('place')]:
        if not item.get('image'): raise ValueError('Add an image for '+item['name']+' before generating a continuity-linked shot.')
        refs.append(item['image']);lines.append('@Image'+str(len(refs))+': '+item['name']+'. Preserve '+item.get('description','identity and appearance')+'.')
    if shot.get('image'):
        refs.append(shot['image']);lines.append('@Image'+str(len(refs))+': approved composition/first-frame reference; preserve its subject and environment.')
    if len(refs)>9: raise ValueError('Use no more than nine combined actor, location and shot references.')
    prompt='\n'.join([board['brief'],*lines,'Shot '+shot['id']+': '+shot['direction'],
                     'Framing: '+shot.get('frame','')+'. Lens impression: '+shot.get('lens','')+'.',
                     'Visual style: '+STYLES.get(board['style'],board['style']),
                     ('Motion: '+shot.get('motion','')+'. Duration: '+str(shot['duration'])+' seconds.') if kind=='video' else 'Create one still image; preserve reference identity and intentional composition.',
                     'Continuity / corrections: '+shot.get('notes','')])
    if len(prompt)>4000: raise ValueError('Shorten the brief or shot direction to fit the image/video prompt budget.')
    payload={'model':MODELS['video' if kind=='video' else 'edit' if refs else 'still'],'prompt':prompt}
    if kind=='video':
        payload.update(duration=shot['duration'],aspect_ratio=board['ratio'],resolution='720p',generate_audio=False,provider='bytedance')
        if refs: payload['image_urls']=refs
        if shot.get('last_image'):
            if len(refs)!=1: raise ValueError('First/last-frame mode needs exactly one shot image and no cast/location reference inputs. Use the approved composite still.')
            payload['image_url']=refs[0];payload.pop('image_urls',None);payload['last_image_url']=shot['last_image']
        if shot.get('motion_reference'):
            payload['video_urls']=[shot['motion_reference']]
            payload['prompt']+='\nUse @Video1 for movement timing and camera reference; preserve the linked cast and place.'
        if shot.get('audio'):
            if not refs and not shot.get('motion_reference'): raise ValueError('Audio guidance also needs an image or video reference.')
            payload['audio_urls']=[shot['audio']];payload['generate_audio']=True
            payload['prompt']+='\nUse @Audio1 as the exact performance reference; preserve words and voice identity. Check output against the original.'
    else:
        payload.update(image_size={'width':board['width'],'height':board['height']},num_images=1)
        if refs: payload['image_urls']=refs
    return payload

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

def provider_call(path,payload=None):
    credential=key()
    if not credential: raise ValueError('AIMLAPI is not connected in this server environment.')
    req=urllib.request.Request('https://api.aimlapi.com'+path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={'Authorization':'Bearer '+credential,'Content-Type':'application/json','Accept':'application/json','User-Agent':'CompanyBrain/1.0'})
    try:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=150) as res:
            raw=res.read(3_000_001)
            if len(raw)>3_000_000: raise RuntimeError('Provider response exceeded the supported size; inspect the recorded job before retrying.')
            return json.loads(raw)
    except urllib.error.HTTPError as error:
        raise RuntimeError('AIMLAPI returned HTTP '+str(error.code)+'. No automatic retry was made.') from None
    except (OSError,ValueError):
        raise RuntimeError('AIMLAPI outcome is uncertain. Check this job before creating another paid request.') from None

def job_path(root,ident):
    if not re.fullmatch(r'[a-f0-9]{32}',ident): raise ValueError('Invalid creative job.')
    return Path(root)/'runtime/creative/jobs'/(ident+'.json')

def submit(brain,p,request_id):
    path=job_path(brain.root,request_id)
    if path.exists(): return json.loads(path.read_text(encoding='utf-8'))
    if p.get('paid_authorized') is not True: raise ValueError('Authorize this one paid generation before submitting.')
    record=brain.get('memory',p['id'])
    if record['archived'] or record['version']!=p['version']: raise ValueError('The board changed. Reload and review the shot first.')
    if not key(): raise ValueError('AIMLAPI is not connected in this server environment.')
    payload=compile_shot(record['data']['board'],p['shot_id'],p['media'],brain.root)
    job={'id':request_id,'board_id':p['id'],'board_version':p['version'],'shot_id':p['shot_id'],
         'media':p['media'],'state':'submitting','created':stamp(),'payload':payload,'provider':'AIMLAPI','paid_authorized':True}
    atomic_json(path,job)
    try:
        wire=json.loads(json.dumps(payload))
        for field in ('image_urls','image_url','last_image_url'):
            if field not in wire: continue
            items=wire[field] if isinstance(wire[field],list) else [wire[field]]
            converted=[]
            for value in items:
                if value.startswith('/creative/assets/'):
                    asset=asset_path(brain.root,value.rsplit('/',1)[-1]);mime={'.jpg':'jpeg','.png':'png','.webp':'webp'}[asset.suffix]
                    value='data:image/'+mime+';base64,'+base64.b64encode(asset.read_bytes()).decode()
                converted.append(value)
            wire[field]=converted if isinstance(wire[field],list) else converted[0]
        result=provider_call('/v2/video/generations' if p['media']=='video' else '/v1/images/generations',wire)
        if p['media']=='video' and not isinstance(result.get('id'),str): raise RuntimeError('Provider did not return a generation identity; inspect the account before retrying.')
        job.update(state=result.get('status','completed'),result=result,generation_id=result.get('id'),updated=stamp())
    except Exception as error:
        job.update(state='uncertain',error=str(error),updated=stamp());atomic_json(path,job);raise
    atomic_json(path,job);return job

def poll(root,ident):
    path=job_path(root,ident)
    job=json.loads(path.read_text(encoding='utf-8'))
    if job['media']!='video' or not job.get('generation_id'): return job
    if job['state'] in ('completed','error','failed','canceled'): return job
    result=provider_call('/v2/video/generations?'+urlencode({'generation_id':job['generation_id']}))
    job.update(state=result.get('status','unknown'),result=result,updated=stamp());atomic_json(path,job)
    return job

def read_jobs(root):
    return [json.loads(p.read_text(encoding='utf-8')) for p in sorted((Path(root)/'runtime/creative/jobs').glob('*.json'),key=lambda x:x.stat().st_mtime,reverse=True)[:100]]

def dispatch(brain,action,p,request_id):
    if action=='creative-save': return save_board(brain,p)
    if action=='creative-image': return import_image(brain.root,p['image'])
    if action=='creative-generate': return submit(brain,p,request_id)
    if action=='creative-poll': return poll(brain.root,p['job_id'])
    if action=='creative-preflight':
        result=provider_call('/v1/models');ids={x['id'] for x in result.get('data',[]) if isinstance(x,dict) and 'id' in x}
        report={'checked':stamp(),'connected':True,'models':{k:{'id':v,'listed':v in ids} for k,v in MODELS.items()},'note':'Catalog access checked. Paid generation is not tested by this check.'}
        atomic_json(Path(brain.root)/'runtime/creative/connection.json',report);return report
    raise ValueError('Unknown creative operation.')
