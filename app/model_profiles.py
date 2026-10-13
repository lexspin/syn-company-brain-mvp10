"""Owner-selected Codex profiles; model effort and speed are independent."""
import re

PROFILES={
    'light':{'model':'gpt-6-luna','reasoning_effort':'low','service_tier':'default'},
    'routine':{'model':'gpt-6.1-sol','reasoning_effort':'medium','service_tier':'default'},
    'thinking':{'model':'gpt-6-astra','reasoning_effort':'medium','service_tier':'default'},
    'innovation':{'model':'gpt-6-astra','reasoning_effort':'ultra','service_tier':'default'},
}
EFFORTS={
    'gpt-6-luna':{'low','medium','high','xhigh','max'},
    'gpt-6.1-sol':{'low','medium','high','xhigh','max','ultra'},
    'gpt-6-astra':{'low','medium','high','xhigh','max','ultra'},
}

def resolve(model='',reasoning_effort='',service_tier='default',model_profile=''):
    values={'model':model,'reasoning_effort':reasoning_effort,'service_tier':service_tier,'model_profile':model_profile}
    if any(not isinstance(v,str) for v in values.values()):raise ValueError('Model profile settings must be strings.')
    if model_profile=='custom':
        if not model or not reasoning_effort:raise ValueError('Custom profiles require an explicit model and effort.')
        model_profile=''
    if model_profile:
        if model_profile not in PROFILES:raise ValueError('Unknown working profile.')
        chosen=PROFILES[model_profile]
        for key in ('model','reasoning_effort','service_tier'):
            if values[key] and values[key]!=chosen[key]:raise ValueError('Working profile conflicts with '+key+'.')
        return dict(chosen,model_profile=model_profile)
    model=model or PROFILES['routine']['model']
    reasoning_effort=reasoning_effort or 'medium'
    if model not in EFFORTS:raise ValueError('Choose a supported Company Brain model.')
    if reasoning_effort not in EFFORTS[model]:raise ValueError('Reasoning effort is not supported for this model.')
    if service_tier not in ('','default'):raise ValueError('Company Brain uses standard speed (default service tier).')
    selected={'model':model,'reasoning_effort':reasoning_effort,'service_tier':'default'}
    return selected|{'model_profile':next((key for key,value in PROFILES.items() if value==selected),'custom')}

def for_agent(data):
    return resolve(**{key:data.get(key,'default' if key=='service_tier' else '') for key in ('model','reasoning_effort','service_tier','model_profile')})

def automatic_eligible(data,prompt):
    """Ultra is opt-in; ordinary creativity or vague requests are insufficient."""
    if for_agent(data)['reasoning_effort']!='ultra':return True
    text=prompt.lower()
    if re.search(r"\b(?:no|not|never|without|avoid|skip|don['’]t)\b[^.!?\n]{0,40}\b(?:innovation|innovate|inovation|ultra)\b",text):return False
    return bool(re.search(r'\binnovate\b',text)
                or re.search(r'^\s*(?:innovation|inovation)\s*[:.!?]?\s*$',text)
                or re.search(r'\b(?:use|select|choose)\s+(?:(?:the|astra)\s+)?(?:ultra|innovation(?:\s+director)?)\b',text)
                or re.search(r'\b(?:develop|create|design|propose|explore|generate|plan|start|run)\b[^.!?\n]{0,50}\b(?:innovation|inovation)\b',text))
