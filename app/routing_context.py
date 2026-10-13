"""Compact discovery cards; full instructions are loaded only after selection."""
import json
import re
from pathlib import Path
from model_profiles import for_agent


def cards(brain, agents):
    result=[]
    for agent in agents:
        d=agent['data']
        skills=[brain.get('skill',id) for id in d.get('skills',[])]
        result.append({'id':agent['id'],'version':agent['version'],'name':d['name'],
                       'purpose':d.get('purpose',d.get('scope',''))[:240], 'scope':d.get('scope','')[:180],
                       'level':d.get('level','specialist'), 'capabilities':d.get('tools',[]),
                       'working_profile':for_agent(d),
                       'skills':[{'id':s['id'],'version':s['version'],'name':s['data']['name'],
                                  'purpose':s['data'].get('purpose',s['data'].get('description',''))[:160]} for s in skills]})
    return result


def relevant_connections(root, query, limit=4):
    """Catalog facts are host availability, never an executable app permission."""
    path=Path(root)/'docs/CONNECTION-CATALOG.json'
    if not path.exists(): return []
    connections=json.loads(path.read_text(encoding='utf-8')).get('connections',[])
    tokens=set(re.findall(r'[a-z0-9]+',query.lower()))-{'the','and','with','from','this','that','brain','company','tool','tools'}
    ranked=[]
    for connection in connections:
        # Sensitive specialist services require an explicit namespace reference.
        id=connection['id']
        if any(x in id for x in ('hotline','safety_settings')) and id.lower() not in query.lower(): continue
        words=set(re.findall(r'[a-z0-9]+',id.lower()))
        names=connection.get('tool_names',[])
        matches=[name for name in names if tokens & set(re.findall(r'[a-z0-9]+',name.lower()))]
        score=3*len(tokens & words)+min(len(matches),3)
        if score:
            ranked.append((score,{'id':id,'status':connection.get('status','unverified'),
                'v2_execution':connection.get('v2_execution','not-connected-to-cli'),
                'relevant_tool_names':matches[:4], 'authority':'Catalog only; no execution from this chat.'}))
    return [entry for _,entry in sorted(ranked,key=lambda x:(-x[0],x[1]['id']))[:limit]]
