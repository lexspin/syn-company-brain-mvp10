"""Finite next-action policy for agent loops. Does not execute effects or grant authority.

Native skills can run this against an observed step before choosing continuation.
Durability and ownership remain the canonical command queue's responsibility.
"""
import argparse
import json
from pathlib import Path


def decide(s):
    required={'attempt','max_attempts','elapsed_seconds','timeout_seconds','effect','outcome',
              'sources_current','authority_current','cancelled','acceptance_passed','receipt_verified'}
    if not isinstance(s,dict) or set(s)!=required:
        raise ValueError('Supply exactly the documented observation fields.')
    for key in ('attempt','max_attempts','elapsed_seconds','timeout_seconds'):
        if type(s[key]) is not int or s[key]<0: raise ValueError('Counters must be nonnegative integers.')
    if not 1<=s['max_attempts']<=10 or not 1<=s['timeout_seconds']<=86400:
        raise ValueError('Use 1–10 attempts and a 1–86400 second time budget.')
    for key in ('sources_current','authority_current','cancelled','acceptance_passed','receipt_verified'):
        if type(s[key]) is not bool: raise ValueError('Observation flags must be booleans.')
    if s['effect'] not in ('read-only','idempotent','non-idempotent'):
        raise ValueError('Unknown effect classification.')
    if s['outcome'] not in ('not-started','succeeded','retryable-failure','permanent-failure','uncertain'):
        raise ValueError('Unknown observed outcome.')
    def result(action, reason, delay=0):
        return {'action':action,'reason':reason,'retry_after_seconds':delay,
                'authority':'Advisory policy only; execute through the current owned workflow contract.'}
    # An uncertain effect always needs reconciliation, including after cancellation or budget exhaustion.
    if s['outcome']=='uncertain': return result('reconcile','Recover the original receipt; do not repeat the effect.')
    if s['cancelled']: return result('stop','Cancellation recorded; retain any completed partial result.')
    if not s['authority_current']: return result('blocked','Current authority does not cover continuation.')
    if not s['sources_current']: return result('replan','Bound sources or instructions changed; preserve this attempt.')
    if s['outcome']=='succeeded':
        if s['receipt_verified'] and s['acceptance_passed']:
            return result('complete','Execution receipt and acceptance are both recorded.')
        return result('review','Execution is not completion; check the result without replaying the effect.')
    if s['outcome']=='permanent-failure': return result('stop','Permanent failure; retain the reason and evidence.')
    if s['attempt']>=s['max_attempts'] or s['elapsed_seconds']>=s['timeout_seconds']:
        return result('stop','Attempt or time budget exhausted.')
    if s['outcome']=='retryable-failure':
        if s['effect']=='non-idempotent':
            return result('reconcile','A side effect cannot be safely retried without provider reconciliation.')
        delay=min(60,2**min(s['attempt'],6))
        if s['elapsed_seconds']+delay>=s['timeout_seconds']:
            return result('stop','The backoff would exhaust the time budget.')
        return result('retry','Retry only this failed safe step with its existing logical operation identity.',delay)
    return result('execute','One step may proceed after the runtime confirms ownership and capability.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('observation',type=Path)
    args=parser.parse_args()
    try: print(json.dumps(decide(json.loads(args.observation.read_text(encoding='utf-8'))),indent=2))
    except (ValueError,OSError) as error: parser.exit(2,str(error)+'\n')
