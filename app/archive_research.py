"""Explicit research capture with provenance, versioned links and stable identity.

Capturing text into the accepted library is an owner decision to retain it; it is
not factual verification. No model call or connector fetch occurs here. Eligible
chat answers may also be retained by the separate authorized answer-memory path.
"""
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from brain import digest

KEY=re.compile(r'[A-Za-z0-9_-]{8,128}\Z')
TURN=re.compile(r'[a-f0-9]{32}\Z')
UNVERIFIED='Captured research for reuse; source support and factual accuracy have not been independently verified.'

def _links(brain,project_id,skill_ids,extra=()):
    if not isinstance(project_id,str):raise ValueError('Project must be an ID or blank.')
    if skill_ids is None:skill_ids=[]
    if not isinstance(skill_ids,list) or len(skill_ids)>30 or not all(isinstance(id,str) for id in skill_ids):raise ValueError('Skills must be a list of up to 30 registered IDs.')
    refs=list(extra)
    if project_id:
        project=brain.get('project',project_id)
        if project['archived']:raise ValueError('Choose an active project before linking this capture.')
        refs.append('project:'+project_id)
    for id in skill_ids:
        skill=brain.get('skill',id)
        if skill['archived']:raise ValueError('Choose active skills before linking this capture.')
        refs.append('skill:'+id)
    return sorted(set(refs))

def _save(brain,id,data,fingerprint,refs):
    try:existing=brain.get('memory',id)
    except ValueError:existing=None
    if existing:
        if existing['data'].get('capture_fingerprint')!=fingerprint:raise ValueError('This archive identity already belongs to different research. Use a new request key for a distinct capture.')
        if existing['archived']:raise ValueError('This research capture is archived. Restore its existing library record before updating links.')
        combined=sorted(set(existing['data'].get('refs',[]))|set(refs))
        if combined==sorted(existing['data'].get('refs',[])):
            result=existing;status='existing'
        else:
            result=brain.save('memory',id,existing['data']|{'refs':combined},existing['version']);status='linked'
    else:
        result=brain.save('memory',id,data|{'refs':refs,'capture_fingerprint':fingerprint});status='created'
    linked=[];warnings=[]
    # These reciprocal links are what makes a later project/skill lookup find the
    # capture. Never change original source memories just to add a backlink.
    for ref in result['data'].get('refs',[]):
        kind,owner_id=ref.split(':',1)
        if kind not in ('project','skill'):continue
        owner=brain.get(kind,owner_id)
        if owner['archived']:
            warnings.append(ref+' is archived; its historical link was preserved without editing it.');continue
        target='memory:'+id
        if target not in owner['data'].get('refs',[]):
            try:owner=brain.save(kind,owner_id,owner['data']|{'refs':list(owner['data'].get('refs',[]))+[target]},owner['version'])
            except Exception as error:raise ValueError('Research was saved as '+id+', but updating '+ref+' failed: '+str(error)+'. Retry the same archive request after correcting that link; the capture will not be duplicated.') from error
            linked.append({'kind':kind,'id':owner_id,'version':owner['version']})
    fresh=brain.memory_freshness().get(id,{'current':False,'reason':'Capture is not current.'})
    return result|{'capture_status':status,'source_current':fresh['current'],'source_note':fresh['reason'],'updated_links':linked,'link_warnings':warnings}

def capture(brain,turn_id,project_id='',skill_ids=None):
    """Archive one completed in-app answer only after an explicit owner command."""
    if not isinstance(turn_id,str) or not TURN.fullmatch(turn_id):raise ValueError('Choose a completed chat turn to archive.')
    with brain.lock:
        trace=brain.chat_turn(turn_id)
        if trace['state']!='completed':raise ValueError('Only a completed specialist answer can be saved to the library.')
        answers=[a for a in trace['attempts'] if a['stage']=='answer' and a['state']=='completed']
        if len(answers)!=1:raise ValueError('The turn must contain exactly one completed specialist answer.')
        content=answers[0]['output']
        if not isinstance(content,str) or not content.strip() or len(content)>100000:raise ValueError('The full answer must contain 1–100000 characters. Capture an explicitly selected excerpt separately if needed.')
        source_versions={r['id']:r['version'] for r in trace['dependencies'] if r['kind']=='memory'}
        configuration_versions={r['kind']+':'+r['id']:r['version'] for r in trace['dependencies'] if r['kind']!='memory'}
        context_refs=['memory:'+id for id in source_versions]
        context_refs += [ref for ref in configuration_versions if ref.startswith(('skill:','project:'))]
        if trace.get('selected_agent'):context_refs.append('agent:'+trace['selected_agent'])
        refs=_links(brain,project_id,skill_ids,context_refs)
        # Automatic retention and the explicit archive action share one home for
        # the same completed answer. Preserve the cache's original evidence and
        # fingerprint; this command only adds the requested connections.
        try:retained=brain.get('memory','answer-'+turn_id)
        except ValueError:retained=None
        if retained:
            retained_data=retained['data']
            if (retained_data.get('type')!='l2-answer-cache'
                or retained_data.get('capture',{}).get('turn_id')!=turn_id
                or retained_data.get('content')!=content
                or retained_data.get('capture',{}).get('answer_sha256')!=digest(content)
                or not retained_data.get('capture_fingerprint')):
                raise ValueError('The existing retained answer no longer matches this completed turn. Review its version history before archiving.')
            return _save(brain,retained['id'],retained_data,retained_data['capture_fingerprint'],refs)
        provenance={'kind':'chat','turn_id':turn_id,'session':trace['session'],'answer_attempt_id':answers[0]['id'],'captured_answer_sha256':digest(content),'completed_at':trace['updated']}
        fingerprint=digest(json.dumps(provenance,sort_keys=True)+content)
        cited=set(re.findall(r'\[([a-z0-9][a-z0-9-]{0,63})@([0-9]+)\]',content))
        cited_versions={id:int(v) for id,v in cited if source_versions.get(id)==int(v)}
        title=trace['request'].strip().splitlines()[0][:110] or 'Research response'
        data={'name':'Research: '+title,'type':'research-capture','status':'accepted','content':content,
              'source':'Explicit owner archive of completed Company Brain chat turn '+turn_id,
              'evidence_type':UNVERIFIED,'validation':{'status':'owner-retained-unverified-research','scope':UNVERIFIED},
              'capture':provenance,'original_request':trace['request'],'selected_agent':trace['selected_agent'],
              'source_versions':source_versions,'cited_source_versions':cited_versions,'configuration_versions':configuration_versions}
        return _save(brain,'research-'+turn_id,data,fingerprint,refs)

def capture_source(brain,title,content,provenance,request_key,project_id='',skill_ids=None):
    """Archive explicitly supplied Codex/document research without fabricating a chat turn."""
    if not isinstance(title,str) or not 1<=len(title.strip())<=180:raise ValueError('Provide a research title of 1–180 characters.')
    if not isinstance(content,str) or not content.strip() or len(content)>100000:raise ValueError('Research content must contain 1–100000 characters.')
    if not isinstance(request_key,str) or not KEY.fullmatch(request_key):raise ValueError('A stable 8–128 character archive request key is required.')
    allowed={'chat_id','source_urls','source_file','source_sha256','source_title','captured_by'}
    if not isinstance(provenance,dict) or provenance.keys()-allowed:raise ValueError('Provide only supported provenance fields: '+', '.join(sorted(allowed)))
    for key in allowed-{'source_urls'}:
        if key in provenance and (not isinstance(provenance[key],str) or len(provenance[key])>2048):raise ValueError('Invalid provenance field: '+key)
    urls=provenance.get('source_urls',[])
    if not isinstance(urls,list) or len(urls)>30:raise ValueError('Provide at most 30 source URLs.')
    for url in urls:
        if not isinstance(url,str) or len(url)>2048:raise ValueError('Invalid source URL.')
        parsed=urlsplit(url)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:raise ValueError('Sources must be HTTP(S) URLs without embedded credentials.')
    if provenance.get('source_sha256') and not re.fullmatch('[a-fA-F0-9]{64}',provenance['source_sha256']):raise ValueError('Source SHA256 must contain 64 hexadecimal characters.')
    if provenance.get('source_file') and not Path(provenance['source_file']).is_absolute():raise ValueError('Source file provenance must use an absolute path.')
    if not (provenance.get('chat_id') or provenance.get('source_file') or urls):raise ValueError('Record the source chat, absolute file path, or source URLs.')
    fingerprint=digest(json.dumps({'title':title,'content':content,'provenance':provenance},sort_keys=True,ensure_ascii=False))
    id='research-'+hashlib.sha256(('source:'+request_key).encode()).hexdigest()[:32]
    with brain.lock:
        refs=_links(brain,project_id,skill_ids)
        data={'name':title.strip(),'type':'research-capture','status':'accepted','content':content,
              'source':'Explicit owner archive of supplied research; provenance is recorded as supplied, not independently fetched or verified.',
              'evidence_type':UNVERIFIED,'validation':{'status':'owner-retained-unverified-research','scope':UNVERIFIED},
              'capture':{'kind':'supplied-research','request_key':request_key,'content_sha256':digest(content),'provenance':provenance,'provenance_verification':'supplied by caller'},
              'source_versions':{}}
        return _save(brain,id,data,fingerprint,refs)
