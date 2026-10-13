"""Owner feedback creates a proposal; a separate owner action changes the skill."""
from brain import uid

def propose(brain, skill_id, feedback, session=''):
    if not isinstance(feedback,str) or not 3<=len(feedback.strip())<=8000:
        raise ValueError('Describe the correction in 3–8000 characters.')
    brain.acquire_interactive_worker()
    try:
        skill=brain.get('skill',skill_id)
        if skill['archived']:raise ValueError('Restore this playbook before improving it.')
        traces=brain.chat_turns(session) if session else []
        trace=next((t for t in traces if t.get('state')=='completed' and any(
            d.get('kind')=='skill' and d.get('id')==skill_id and d.get('version')==skill['version']
            for d in t.get('dependencies',[]))),None)
        from codex_runtime import run
        request=('Revise the supplied skill procedure using the owner feedback. Preserve its scope, '
                 'evidence requirements, authority and safety boundaries. Do not invent tools, sources, '
                 'training results or permissions. Return only the complete replacement procedure in Markdown, '
                 'under 8000 characters. Include a normal example, counterexample, and acceptance conditions. '
                 'This is a proposal for review, not an activated change.\n\nCurrent skill:\n'+skill['data']['instructions']+
                 '\n\nOwner feedback:\n'+feedback)
        if trace:
            import json
            context={'request':trace.get('prompt',''),'contract':trace.get('contract',{}),
                     'answer':next((a.get('output','') for a in trace.get('attempts',[]) if a.get('stage')=='answer'),'')}
            request+='\n\nRelated work (unverified model output; use owner feedback as the correction):\n'+json.dumps(context,ensure_ascii=False)[:12000]
        result=run(request,model_profile='routine')
        text=result['text'].strip()
        if not text or len(text)>20000:raise ValueError('Proposal was empty or too long. Refine the feedback and try again.')
        with brain.lock:
            brain.assert_records_fresh([skill])
            data={'name':'Proposed improvement: '+skill['data']['name'], 'type':'skill-improvement',
                  'skill_id':skill_id,'base_version':skill['version'],
                  'before_instructions':skill['data']['instructions'],'proposed_instructions':text,
                  'feedback':feedback,'status':'candidate','content':text,
                  'source':'Owner feedback entered in Company Brain; generated proposal awaits review.',
                  'refs':['skill:'+skill_id],
                  'validation':{'status':'proposal-unreviewed','scope':'Instruction proposal only; example tests have not been executed.'}}
            if trace:data['source_turn_id']=trace['id']
            return brain.save('memory','improvement-'+uid(),data)
    finally:brain.active.release()

def apply(brain, id):
    with brain.lock:
        proposal=brain.get('memory',id);data=proposal['data']
        if data.get('type')!='skill-improvement' or proposal['archived']:
            raise ValueError('Choose an active playbook improvement proposal.')
        if data.get('applied_version'):return proposal
        skill=brain.get('skill',data['skill_id'])
        if skill['archived']:raise ValueError('Restore this playbook before applying changes.')
        # Recover idempotently if the skill save succeeded before a projection error.
        if skill['data'].get('improvement_id')==id:
            updated=skill
        else:
            if skill['version']!=data['base_version']:
                raise ValueError('This playbook has changed since the proposal. Generate a new proposal from its current version.')
            updated=brain.save('skill',skill['id'],skill['data']|{
                'instructions':data['proposed_instructions'],'improvement_id':id,
                'validation':{'status':'owner-reviewed-instructions','scope':'Owner applied this instruction change; production performance is not established.'}},skill['version'])
        return brain.save('memory',id,data|{'status':'accepted','applied_version':updated['version'],
            'source':'Owner-reviewed instruction change applied through Company Brain.',
            'evidence_type':'Instruction decision; not a measured performance improvement.',
            'validation':{'status':'owner-applied','scope':'Instructions updated after explicit owner review.'}},proposal['version'])
