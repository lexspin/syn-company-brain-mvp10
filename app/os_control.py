"""Read-only executive projection over the canonical Brain's published records.

No store, queue or model writes. Evidence labels describe exactly what was read.
"""
from urllib.parse import quote


def record_link(kind, identity):
    return 'http://127.0.0.1:14699/#' + quote(kind, safe='') + '/' + quote(identity, safe='')


def overview(state):
    rows = [r for r in state['objects'] if not r.get('archived')]
    lookup = {r['kind']+':'+r['id']: r for r in rows}
    requests = [r for r in rows if r['kind']=='memory' and r['data'].get('type')=='native-work-request']
    workflows, attention = [], []
    for row in rows:
        if row['kind'] != 'loop':
            continue
        data = row['data']; execution = data.get('execution') or {}
        related = [r for r in requests if r['data'].get('loop_id')==row['id']]
        outcomes = []; problems = []
        for request in related:
            d = request['data']; status = d.get('request_state', 'unknown')
            result = lookup.get('memory:'+str(d.get('result_ref', '')))
            linked = bool(result and result['data'].get('type') != 'native-work-request'
                          and 'loop:'+row['id'] in result['data'].get('refs', [])
                          and d.get('completion_evidence') and d.get('claimant')
                          and d.get('claimed_at') and d.get('completed_at'))
            if status in ('queued', 'running') and d.get('loop_version') != row['version']:
                problems.append('A waiting or running request uses an older workflow. Review it before continuing.')
            if status == 'failed':
                problems.append(d.get('failure_reason') or 'A request failed; inspect its retained evidence.')
            if status == 'completed' and not linked:
                problems.append('A completion record is missing its claim, linked result or check evidence.')
            outcomes.append({'name':d.get('name', request['id']), 'state':status,
                             'href':record_link('memory', request['id']),
                             'evidence':'Result and checks recorded' if status=='completed' and linked else 'Not verified here',
                             'result_href':record_link('memory', result['id']) if result else None})
        missing = [ref for ref in data.get('refs', []) if ref not in lookup]
        # Historical memory references are retained even when superseded; they are not broken configuration.
        missing_config = [ref for ref in missing if not ref.startswith('memory:')]
        if missing_config:
            problems.append('Unavailable configuration links: '+', '.join(missing_config))
        mode = execution.get('type', 'local-steps')
        if mode == 'codex-chat':
            skill = execution.get('skill_id')
            if not skill or 'skill:'+skill not in lookup:
                problems.append('The native procedure is missing its active skill.')
        if mode == 'codex-heartbeat' and not execution.get('automation_id'):
            problems.append('No scheduler connection is recorded.')
        if mode == 'local-steps' and not data.get('steps'):
            problems.append('No executable steps are recorded.')
        card = {'id':row['id'], 'name':data.get('name', row['id']),
                'description':data.get('description', ''), 'href':record_link('loop',row['id']),
                'mode':{'codex-chat':'Native Codex procedure','codex-heartbeat':'Scheduled Codex procedure',
                        'local-steps':'Local step workflow'}.get(mode, 'Other execution contract'),
                'schedule':execution.get('schedule'), 'schedule_status':execution.get('status'),
                'schedule_evidence':'Configuration only; scheduled completion is not established by this view.',
                'outcomes':outcomes, 'problems':list(dict.fromkeys(problems)),
                'status':'Needs attention' if problems else 'Configured', 'version':row['version']}
        workflows.append(card)
        attention.extend({'name':card['name'], 'reason':reason, 'href':card['href']} for reason in card['problems'])
    memory = [r for r in rows if r['kind']=='memory' and r['data'].get('type')!='native-work-request']
    freshness = state.get('memory_freshness', {})
    projects = [{'name':r['data'].get('name',r['id']), 'scope':r['data'].get('scope',''),
                 'href':record_link('project',r['id'])} for r in rows if r['kind']=='project']
    counts = {status:sum(r['data'].get('request_state')==status for r in requests)
              for status in ('queued','running','completed','failed')}
    return {'milestone':'MVP02_AI OS', 'source_root':state.get('root'), 'publication':state.get('_view',{}),
            'worker_busy':state.get('worker_busy'), 'counts':counts, 'projects':projects,
            'workflows':sorted(workflows,key=lambda w:w['name'].casefold()), 'attention':attention,
            'memory':{'total':len(memory), 'current':sum(freshness.get(r['id'],{}).get('current') is True for r in memory),
                      'candidate':sum(r['data'].get('status')=='candidate' for r in memory)},
            'tools':state.get('tools',[]),
            'limits':['This view reads the existing Brain; it does not start workers or add schedules.',
                      'Recorded checks are evidence pointers, not independent proof of result quality.',
                      'Native chats remain the working interface. The local host must be available.']}
