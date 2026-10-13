"""Read-only operating controls projection; canonical module owns admission rules."""
import importlib.util
from pathlib import Path


def operating_view(source_root, state):
    path = Path(source_root)/'app/operating_policy.py'
    spec = importlib.util.spec_from_file_location('canonical_operating_policy_view', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    policy = module.policy_for_root(source_root)
    agents = []
    for record in state.get('objects', []):
        if record.get('kind') != 'agent' or record.get('archived'): continue
        data = record['data']
        agents.append({'id':record['id'], 'name':record.get('display_name') or data.get('name') or record['id'],
            'version':record['version'], 'requested_state':data.get('operating_state'),
            'effective_state':module.effective_state(policy, record),
            'model':data.get('model'), 'reasoning_effort':data.get('reasoning_effort')})
    busy = state.get('worker_busy')
    return {'policy':policy, 'agents':sorted(agents, key=lambda a:a['name'].casefold()),
            'activity':{'worker_busy':busy if type(busy) is bool else None,
                        'source':'Backend-published activity', 'view':state.get('_view', {})},
            'controls_available':True,
            'scope':'Requested admission setting only; already-running work and native chats are not stopped by this control.'}
