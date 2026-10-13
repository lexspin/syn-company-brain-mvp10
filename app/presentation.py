"""Display-only names derived from saved titles and source context; no record writes."""
import re
from pathlib import PurePosixPath

NAME_ALIASES={
    'ml method selection':'Machine learning — choose a method',
    'ml reinforcement learning':'Machine learning — reinforcement learning',
    'ml semi supervised learning':'Machine learning — semi-supervised learning',
    'ml supervised learning':'Machine learning — supervised learning',
    'ml unsupervised learning':'Machine learning — unsupervised learning',
    'ue mcp animation':'Unreal Engine — animation workflow',
    'ue mcp native animation workflow':'Unreal Engine — native animation workflow',
    'ue mcp niagara':'Unreal Engine — Niagara visual effects',
    'ue mcp niagara authoring':'Unreal Engine — Niagara visual effects',
    'ue mcp workflow':'Unreal Engine — editor workflow',
    'ue canvas fractal reveal':'Unreal Engine — canvas fractal reveal',
    'ue5 canvas fractal reveal':'Unreal Engine — canvas fractal reveal',
}


def name_key(value):return re.sub(r'[^a-z0-9]+',' ',str(value).casefold()).strip()


def human_name(value):
    value=str(value).strip()
    if name_key(value) in NAME_ALIASES:return NAME_ALIASES[name_key(value)]
    machine='_' in value or bool(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)+',value))
    if machine:value=re.sub(r'[_-]+',' ',value).title()
    if value.isupper() and len(value)>8:value=value.title()
    value=re.sub(r'\bMl\b','Machine learning',value)
    value=re.sub(r'\bUe(?:5)?\b','Unreal Engine',value)
    value=re.sub(r'\bLinkedin\b','LinkedIn',value)
    value=re.sub(r'\bYoutube\b','YouTube',value)
    value=re.sub(r'\bVoicelab\b','VoiceLab',value)
    value=re.sub(r'\bOpenai\b','OpenAI',value)
    value=re.sub(r'\b(ARMS|MAPS)\b',lambda m:m[0].upper(),value,flags=re.I)
    return re.sub(r'\s+',' ',value).strip()


def source_heading(data):
    content=data.get('content','')
    if not isinstance(content,str):return ''
    match=re.search(r'^#\s+([^\n]+)$',content[:12000],re.M)
    return match[1].strip()[:180] if match else ''


def record_display_name(record,source_titles=None):
    data=record.get('data',{});raw=str(data.get('name') or record.get('id') or 'Saved record')
    part=re.search(r'\s+[—–-]\s+part\s+(\d+)\s*$',raw,re.I)
    suffix=' — part '+part[1] if part else ''
    base=raw[:part.start()] if part else raw
    key=name_key(base);path=data.get('source_path','')
    heading=(source_titles or {}).get(path) or (source_heading(data) if not part or part[1]=='1' else '')
    if key in NAME_ALIASES:return NAME_ALIASES[key]+suffix
    if key=='role brief':
        role=re.sub(r'\s+Role Brief\s*$','',heading,flags=re.I).strip()
        if not role or name_key(role)=='role brief':role=PurePosixPath(str(path).replace('\\','/')).parent.name or 'Team'
        lane=re.search(r'^Lane:\s*(.+)$',str(data.get('content',''))[:12000],re.M|re.I)
        purpose='role and responsibilities'
        if lane:
            purpose=lane[1].strip().rstrip('.')
            terms=purpose.casefold()
            if 'graphics' in terms and 'environment art' in terms:purpose='graphics and environment art'
            elif 'ai/backend' in terms and 'godot' in terms:purpose='AI, backend and Godot systems'
            elif len(purpose)>110:purpose=purpose[:107].rsplit(' ',1)[0]+'…'
        return human_name(role)+' — '+purpose+suffix
    machine='_' in base or bool(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)+',base))
    title=heading if machine and heading else base
    title=human_name(title)
    title=re.sub(r'\s+Mandate$',' — responsibilities',title,flags=re.I)
    return title+suffix


def display_records(records):
    titles={}
    for record in records:
        data=record.get('data',{});path=data.get('source_path')
        part=re.search(r'\s+[—–-]\s+part\s+(\d+)\s*$',str(data.get('name','')),re.I)
        heading=source_heading(data)
        if path and heading and (not part or part[1]=='1'):titles[path]=heading
    return [record|{'display_name':record_display_name(record,titles)} for record in records]
