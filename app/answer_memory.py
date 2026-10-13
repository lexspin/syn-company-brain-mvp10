"""Deterministic L1 reuse of current source-linked L2 answers.

Retention is authorized housekeeping, not factual verification or owner approval.
No model call occurs here. Original answers and source/configuration provenance
remain in their versioned records and operational receipts.
"""
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

BOOKKEEPING = {'refs','historical_source_refs','source_links','reference_links','location','source_path','source_sha256','validation','imported_at'}
CITATION = re.compile(r'\[([a-z0-9][a-z0-9-]{0,63})@([1-9][0-9]*)\]')
LOOKUP = re.compile(r'(?:(?:show|read|get)\s+)?(?:memory:([a-z0-9][a-z0-9-]{0,63})(?:@v?([1-9][0-9]*))?|\[([a-z0-9][a-z0-9-]{0,63})@([1-9][0-9]*)\])\s*[?.]?\Z')
RELATIVE_TIME = re.compile(r'\b(?:today|tomorrow|yesterday|tonight|now|latest|recent|recently|currently)\b|\b(?:this|last|next)\s+(?:week|month|year|hour|day)\b',re.I)
UNVERIFIED = 'Captured source-linked L2 answer for reuse; citations were checked mechanically, not independently verified as facts or approved by the owner.'

def now(): return datetime.now(timezone.utc).isoformat()
def digest(value): return hashlib.sha256(value.encode('utf-8')).hexdigest()
def packed(value): return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',',':'))

def normalize_query(prompt):
    # Case, identifiers, numbers, punctuation and code layout are significant.
    text = prompt.replace('\r\n','\n').strip()
    return text if '\n' in text or '`' in text else ' '.join(text.split())

def role_key(requested): return 'automatic' if requested in ('auto','coordinator') else requested

def semantic_hash(record):
    data = {k:v for k,v in record['data'].items() if k not in BOOKKEEPING}
    if record['kind']=='agent':
        from model_profiles import for_agent
        data = data | {'effective_model_settings':for_agent(record['data'])}
    return digest(packed({'kind':record['kind'],'id':record['id'],'archived':bool(record['archived']),'data':data}))

def context_digest(brain, session, prompt, answer, before=None):
    with brain.connect() as c:
        if before:
            rows=[dict(r) for r in c.execute("SELECT role,text FROM messages WHERE session=? AND role IN ('user','assistant') AND created<=? ORDER BY id DESC LIMIT 60",(session,before))][::-1]
            if not rows or rows[-1]['role']!='user' or rows[-1]['text']!=prompt:
                raise ValueError('Original request context could not be identified.')
            rows.pop()
        else:
            rows=[dict(r) for r in c.execute("SELECT role,text FROM messages WHERE session=? AND role IN ('user','assistant') ORDER BY id DESC LIMIT 60",(session,))][::-1]
    # Repeating this same question/answer adds no new conversational instruction.
    # Any other intervening user request or answer invalidates the reuse context.
    while len(rows)>=2 and rows[-2]['role']=='user' and rows[-1]['role']=='assistant' and normalize_query(rows[-2]['text'])==normalize_query(prompt) and rows[-1]['text']==answer:
        del rows[-2:]
    return digest(packed(rows[-12:]))

def trace_snapshot(brain, turn_id):
    trace = brain.chat_turn(turn_id)
    with brain.connect() as c:
        row = c.execute('SELECT dependencies FROM chat_turns WHERE id=?',(turn_id,)).fetchone()
    return trace, json.loads(row[0])

def _write_replay(brain, session, prompt, requested, selected, content, dependencies, mode, reused, contract):
    turn_id=uuid.uuid4().hex; attempt_id=uuid.uuid4().hex; stamp=now()
    discovery={'layer':'L1','mode':mode,'model_calls':0,'tool_calls':0,'reused_from':reused,
               'evidence':'Current saved records read deterministically; no planner or specialist model was called.'}
    with brain.connect() as c:
        c.execute('INSERT INTO messages(session,role,text,created) VALUES(?,?,?,?)',(session,'user',prompt,stamp))
        c.execute('INSERT INTO chat_turns VALUES(?,?,?,?,?,?,?,?,?,?,?)',(turn_id,session,requested,selected,'completed',prompt,packed(contract),packed(dependencies),'',stamp,stamp))
        c.execute('INSERT INTO chat_attempts VALUES(?,?,?,?,?,?,?,?,?,?)',(attempt_id,turn_id,'l1-reuse' if mode=='l1_reuse' else 'l1-lookup',selected,'completed',packed(discovery),content,'',stamp,stamp))
        c.execute('INSERT INTO messages(session,role,text,created) VALUES(?,?,?,?)',(session,'assistant',content,stamp))
        brain.event(c,'chat-discovery',turn_id,packed(discovery))
        brain.event(c,'chat-completed',turn_id,mode+': zero model calls')
    return {'text':content,'turn_id':turn_id,'trace':brain.chat_turn(turn_id),'mode':mode,'model_calls':0,'tool_calls':[],'reused_from':reused}

def recall_known(brain, session, prompt, agent_id, project=None):
    """Return a durable deterministic response, or None for normal L1/L2 work.

    Caller owns the interactive worker lock. Project is its validated record.
    """
    with brain.lock:
        if agent_id not in ('auto','coordinator'):
            requested = brain.get('agent',agent_id)
            if requested['archived']: raise ValueError('Agent is archived.')
            brain.chat_skills(requested)
        project_id = project['id'] if project else ''
        current = brain.list(archived=True); by_key={(r['kind'],r['id']):r for r in current}
        freshness=brain.memory_freshness([r for r in current if r['kind']=='memory'])
        query_hash=digest(normalize_query(prompt))
        candidates=[] if RELATIVE_TIME.search(prompt) else [r for r in current if r['kind']=='memory' and not r['archived'] and r['data'].get('type')=='l2-answer-cache']
        for memory in sorted(candidates,key=lambda r:r['updated'],reverse=True):
            data=memory['data']; cache=data.get('answer_cache',{})
            if cache.get('query_hash')!=query_hash or cache.get('project_id')!=project_id or cache.get('requested_role')!=role_key(agent_id): continue
            if not freshness.get(memory['id'],{}).get('current') or digest(data.get('content',''))!=cache.get('answer_sha256'): continue
            if context_digest(brain,session,prompt,data['content'])!=cache.get('history_sha256'): continue
            dependencies=[memory]; valid=True
            for binding in cache.get('config_signatures',[]):
                record=by_key.get((binding['kind'],binding['id']))
                if not record or record['archived'] or semantic_hash(record)!=binding['sha256']: valid=False; break
                dependencies.append(record)
            if not valid: continue
            for id,version in cache.get('context_source_versions',{}).items():
                source=by_key.get(('memory',id))
                if not source or source['version']!=version or not freshness.get(id,{}).get('current'): valid=False;break
                dependencies.append(source)
            if not valid or not data.get('source_versions'): continue
            reused={'kind':'memory','id':memory['id'],'version':memory['version'],'original_turn_id':data['capture']['turn_id']}
            return _write_replay(brain,session,prompt,agent_id,data['selected_agent'],data['content'],dependencies,'l1_reuse',reused,data['task_contract'])
        lookup=LOOKUP.fullmatch(prompt.strip())
        if lookup:
            id=lookup.group(1) or lookup.group(3); version=lookup.group(2) or lookup.group(4)
            source=by_key.get(('memory',id))
            if source and freshness.get(id,{}).get('current') and (not version or source['version']==int(version)):
                content=source['data']['name']+' ['+id+'@'+str(source['version'])+']\n\n'+source['data']['content']
                content+='\n\nSource status: '+source['data'].get('evidence_type','Saved record; factual verification is not implied.')
                reused={'kind':'memory','id':id,'version':source['version'],'original_turn_id':''}
                contract={'agent_id':agent_id,'task':'Read the explicitly requested current memory record.','success_criteria':['Return its saved text and exact version.'],'missing_information':[]}
                dependencies=[source,*([project] if project else [])]
                return _write_replay(brain,session,prompt,agent_id,agent_id,content,dependencies,'l1_lookup',reused,contract)
        return None

def retain_answer(brain, result):
    """Retain an eligible completed answer after Brain.chat releases its lock.

    Return result additions. Ineligible answers are normal skips. The caller
    records unexpected failures as warnings without retrying the model call.
    """
    if not isinstance(result,dict) or not result.get('turn_id') or result.get('mode') in ('l1_reuse','l1_lookup'): return {}
    with brain.lock:
        trace,snapshot=trace_snapshot(brain,result['turn_id'])
        if RELATIVE_TIME.search(trace['request']): return {'retention_skipped':'Relative-time questions require fresh reasoning rather than a saved exact-query answer.'}
        answers=[a for a in trace['attempts'] if a['stage']=='answer' and a['state']=='completed']
        if trace['state']!='completed' or len(answers)!=1 or trace['contract'].get('missing_information')!=[]:
            return {'retention_skipped':'The answer is incomplete or its task contract has unresolved information gaps.'}
        content=answers[0]['output']
        if not content.strip() or len(content)>100000 or result.get('text')!=content: return {'retention_skipped':'The returned answer is not the exact bounded completed artifact.'}
        citations=CITATION.findall(content); bracketed=re.findall(r'\[[^\]\n]*@[^\]\n]*\]',content)
        if not citations or len(citations)!=len(bracketed): return {'retention_skipped':'At least one exact source citation and no malformed citation are required.'}
        sources={r['id']:r for r in snapshot if r['kind']=='memory'}; cited={}
        for id,version in citations:
            if id not in sources or sources[id]['version']!=int(version): return {'retention_skipped':'A cited source was not part of this answer’s exact evidence.'}
            cited[id]=int(version)
        try: brain.assert_records_fresh([sources[id] for id in sources])
        except ValueError: return {'retention_skipped':'Source context changed before retention.'}
        configs=[r for r in snapshot if r['kind'] in ('agent','skill','project')]
        signatures=[]
        for record in configs:
            current=brain.get(record['kind'],record['id'])
            if current['archived'] or semantic_hash(current)!=semantic_hash(record): return {'retention_skipped':'Relevant instructions or project scope changed before retention.'}
            signatures.append({'kind':record['kind'],'id':record['id'],'sha256':semantic_hash(record)})
        projects=[r for r in configs if r['kind']=='project']; project_id=projects[0]['id'] if projects else ''
        selected=next((r for r in configs if r['kind']=='agent' and r['id']==trace['selected_agent']),None)
        if selected is None: return {'retention_skipped':'The selected specialist has no recorded configuration.'}
        skills=list(selected['data'].get('skills',[]))
        cache={'schema':1,'query_hash':digest(normalize_query(trace['request'])),'project_id':project_id,'requested_role':role_key(trace['requested_agent']),
               'answer_sha256':digest(content),'history_sha256':context_digest(brain,trace['session'],trace['request'],content,before=trace['created']),
               'config_signatures':signatures,'context_source_versions':{id:r['version'] for id,r in sources.items()}}
        provenance={'kind':'completed-l2-answer','turn_id':trace['id'],'session':trace['session'],'answer_attempt_id':answers[0]['id'],
                    'answer_sha256':digest(content),'completed_at':trace['updated'],'retention_authority':'Standing owner instruction for source-linked answer reuse'}
        title=trace['request'].strip().splitlines()[0][:110]
        data={'name':'Known answer: '+title,'type':'l2-answer-cache','status':'accepted','content':content,
              'source':'Automatically retained completed L2 answer '+trace['id']+' under standing owner instruction.',
              'evidence_type':UNVERIFIED,'validation':{'status':'source-links-current-answer-not-fact-verified','scope':UNVERIFIED},
              'capture':provenance,'original_request':trace['request'],'selected_agent':trace['selected_agent'],'task_contract':trace['contract'],
              'source_versions':cited,'configuration_versions':{r['kind']+':'+r['id']:r['version'] for r in configs},'answer_cache':cache}
        from archive_research import _links, _save
        refs=_links(brain,project_id,skills,['memory:'+id for id in cited]+['agent:'+trace['selected_agent']])
        # An explicit capture may already be the canonical home (for example,
        # after recovery of a previously completed turn). Never fork its answer
        # into a second record merely to enable the optimization.
        try:existing_capture=brain.get('memory','research-'+trace['id'])
        except ValueError:existing_capture=None
        if existing_capture:
            previous=existing_capture['data']
            if previous.get('capture',{}).get('turn_id')!=trace['id'] or previous.get('content')!=content or not previous.get('capture_fingerprint'):
                raise ValueError('The existing explicit capture does not match this completed answer.')
            saved=_save(brain,existing_capture['id'],previous,previous['capture_fingerprint'],refs)
            return {'memory_saved':{'id':saved['id'],'version':saved['version'],'source_current':saved['source_current']},'retention_note':'The original explicit library capture remains the canonical answer; no additional cache record was created.'}
        fingerprint=digest(packed(provenance)+content)
        saved=_save(brain,'answer-'+trace['id'],data,fingerprint,refs)
        with brain.connect() as c: brain.event(c,'chat-answer-retained',trace['id'],packed({'id':saved['id'],'version':saved['version'],'authority':'standing-owner-retention','factual_verification':False}))
        return {'memory_saved':{'id':saved['id'],'version':saved['version'],'source_current':saved['source_current']},'retention_note':UNVERIFIED}
