"""Read-only comparison of published workflow metadata and actual host schedules.

An observation is neither a scheduler update nor proof that a workflow ran.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tomllib


def audit(state, host_directory):
    rows = [r for r in state['objects'] if not r.get('archived')]
    loops = [r for r in rows if r['kind'] == 'loop']
    output, findings = [], []
    for row in loops:
        data = row['data']; execution = data.get('execution', {})
        item = {'id': row['id'], 'version': row['version'], 'name': data['name'],
                'executor': execution.get('type', 'local-steps'),
                'trigger': execution.get('trigger', execution.get('schedule', 'explicit-start')),
                'configured_status': execution.get('status'), 'host_status': None,
                'attempt_limit': data.get('max_attempts'),
                'skills': [r for r in data.get('refs', []) if r.startswith('skill:')],
                'handoffs': [r for r in data.get('refs', []) if r.startswith('loop:')]}
        if execution.get('type') == 'codex-heartbeat':
            identity = execution.get('automation_id', '')
            # IDs are already validated at save; protect standalone callers too.
            if not identity or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in identity):
                findings.append({'loop': row['id'], 'code': 'invalid-host-id'})
            else:
                path = Path(host_directory)/identity/'automation.toml'
                try:
                    host = tomllib.loads(path.read_text(encoding='utf-8'))
                    item.update(host_status=host.get('status'), host_rrule=host.get('rrule'), host_source=str(path))
                    if host.get('status') not in {'ACTIVE', 'PAUSED'}:
                        findings.append({'loop': row['id'], 'code': 'unknown-host-status'})
                    elif execution.get('status') != host['status']:
                        findings.append({'loop': row['id'], 'code': 'host-status-mismatch',
                                         'recorded': execution.get('status'), 'observed': host['status']})
                except (OSError, ValueError) as error:
                    findings.append({'loop': row['id'], 'code': 'host-unavailable', 'error_type': type(error).__name__})
        output.append(item)
    policy = next((r for r in rows if r['kind']=='stack' and r['id']=='operating-policy'), None)
    from operating_policy import interpret
    effective = interpret(policy, previously_configured=True)['effective_state']
    for item in output:
        if effective != 'idle' and item['host_status'] == 'ACTIVE':
            findings.append({'loop': item['id'], 'code': 'host-wakeup-outside-idle', 'operating_state': effective})
    requests = [{'id':r['id'], 'version':r['version'], 'state':r['data'].get('request_state'),
                 'loop':r['data'].get('loop_id'), 'claimant':r['data'].get('claimant')}
                for r in rows if r['kind']=='memory' and r['data'].get('type')=='native-work-request'
                and r['data'].get('request_state') in {'queued','running'}]
    return {'observed_at':datetime.now(timezone.utc).isoformat(), 'publication':state.get('_view'),
            'operating_state':effective, 'loops':output, 'outstanding_requests':requests,
            'findings':findings, 'scope':'Read-only configuration observation; no execution or schedule changes.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-directory', type=Path, default=Path.home()/'.codex/automations')
    args=parser.parse_args()
    from routed_execution import PublishedClient
    try:
        report=audit(PublishedClient().state(), args.host_directory)
    except (ValueError, OSError):
        print(json.dumps({'status':'unverified', 'findings':[{'code':'publication-unavailable-or-stale'}],
                          'next_action':'Check the canonical publisher and read a fresh snapshot before changing records. No changes were made.'}))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__': raise SystemExit(main())
