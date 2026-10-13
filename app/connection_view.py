"""Expose recorded connection evidence without inventing live plugin health."""
import json
import hashlib
from pathlib import Path


def checked_operations(root, identity, probe):
    """Bind displayed outcomes to a retained, hash-pinned operation report."""
    if not isinstance(probe, dict): return []
    manifest=probe.get('operation_evidence', {})
    try:
        base=Path(root).resolve()
        path=(base/manifest['path']).resolve()
        if not path.is_relative_to(base) or path.stat().st_size>1_000_000: return []
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=manifest['sha256']: return []
        entries=json.loads(raw)
        if not isinstance(entries,list): return []
        result=[]
        for check in probe.get('tool_checks',[]):
            if check.get('status') not in ('returned','failed'): continue
            for e in entries:
                if (isinstance(e,dict) and e.get('id')==identity and e.get('operation')==check.get('tool')
                    and e.get('status')==('verified-operation' if check['status']=='returned' else 'failed')
                    and isinstance(e.get('result'),str) and e['result'].strip() and e.get('observed_at')):
                    result.append({'tool':e['operation'],'label':e['operation'].replace('_',' '),
                        'status':check['status'],'result':e['result']+' '+e.get('scope',''),
                        'observed_at':e['observed_at'],'evidence_validated':True})
                    break
        return result
    except (OSError,ValueError,KeyError,TypeError): return []


def connections(source_root, state):
    path=Path(source_root)/'docs/CONNECTION-CATALOG.json'
    catalog=json.loads(path.read_text(encoding='utf-8-sig'))
    rows=[]
    for connection in catalog.get('connections',[]):
        identity=connection['id']; tool_names=connection.get('tool_names',[])
        related=[]
        for record in state.get('objects',[]):
            if record.get('archived') or record['kind'] not in ('project','agent','skill','loop'):continue
            data=record['data']; serialized=json.dumps(data)
            assigned=identity in data.get('connection_ids',[]) or 'connection:'+identity in data.get('refs',[])
            referenced=any(tool in serialized for tool in tool_names)
            if assigned or referenced:
                related.append({'kind':record['kind'],'id':record['id'],
                                'name':record.get('display_name') or data.get('name',record['id']),
                                'relationship':'Assigned connection' if assigned else 'Tool reference in instructions'})
        probe=connection.get('probe')
        checked=checked_operations(source_root,identity,probe)
        if probe:
            probe=dict(probe)
            probe['tool_checks']=[next((entry for entry in checked if entry['tool']==check.get('tool') and entry['status']==check.get('status')),
                dict(check,evidence_validated=False)) for check in probe.get('tool_checks',[])]
            if checked:
                passed=sum(entry['status']=='returned' for entry in checked)
                failed=sum(entry['status']=='failed' for entry in checked)
                probe['result']=(checked[0]['result'] if len(checked)==1 else
                    f'{passed} checked read operations returned; {failed} failed. Individual checks below show their exact scope.')
                probe['date']=max(entry['observed_at'] for entry in checked)
        rows.append({'id':identity,'name':identity.replace('_',' ').title(),
                     'recorded_status':connection.get('status','unverified'),
                     'execution':connection.get('v2_execution','unverified'),
                     'tool_count':connection.get('tool_count',len(tool_names)),
                     'probe':probe,'related':related,'tools':tool_names,
                     'usage':'No complete per-area usage ledger is recorded in this catalog.'})
    return {'observed_at':catalog.get('observed_at'), 'source':catalog.get('source'),
            'connections':rows,'live_health_checked':False,
            'scope':'Recorded host capabilities and test evidence. This is not an installed-plugin inventory or a live health probe.'}
