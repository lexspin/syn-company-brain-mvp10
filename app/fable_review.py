"""Original claim-observation matrix inspired by the MIT Fable Method judge.

No provider calls, commands, persistence, promotion or task completion. Callers bind
authorized observation callbacks; their truthfulness and effects remain their responsibility.
"""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Claim:
    id: str
    label: str
    expected: str


@dataclass(frozen=True)
class Observation:
    value: str
    evidence_refs: tuple[str, ...]


def _text(value, maximum):
    return (isinstance(value, str) and 0 < len(value) <= maximum
            and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def review_claims(claims, observers):
    """Observe up to 32 named claims once each; exact expected/observed comparison.

    An observed match is only evidence for that claim at this call boundary, not
    proof of semantic quality, an independent reviewer, or whole-task acceptance.
    Missing/error observations require review and are never factual refutations.
    """
    if not isinstance(claims, (list, tuple)) or not 1 <= len(claims) <= 32:
        raise ValueError('Provide between one and 32 claims.')
    if not isinstance(observers, dict):
        raise ValueError('Observers must be a mapping of claim IDs to callbacks.')
    identities = set()
    for claim in claims:
        if (not isinstance(claim, Claim) or not isinstance(claim.id, str)
                or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', claim.id)
                or claim.id in identities or not _text(claim.label, 160)
                or not _text(claim.expected, 1000)):
            raise ValueError('Invalid or duplicate claim identity, label or expectation.')
        identities.add(claim.id)
    if set(observers) - identities or any(not callable(value) for value in observers.values()):
        raise ValueError('Observer IDs must match claims and values must be callable.')
    # Callback effects on caller-owned containers must not change this review's
    # validated scope or swap a later observer after the review has begun.
    claims = tuple(claims)
    observers = dict(observers)
    rows = []
    for claim in claims:
        row = {'id': claim.id, 'label': claim.label, 'expected': claim.expected,
               'observed': None, 'evidence_refs': [], 'status': 'unverified'}
        if claim.id in observers:
            try:
                observed = observers[claim.id]()
                if (not isinstance(observed, Observation) or not _text(observed.value, 1000)
                        or not isinstance(observed.evidence_refs, tuple)
                        or not 1 <= len(observed.evidence_refs) <= 8
                        or any(not _text(ref, 1000) for ref in observed.evidence_refs)):
                    raise ValueError('Invalid observation.')
                row.update(observed=observed.value, evidence_refs=list(observed.evidence_refs),
                           status='observed-match' if observed.value == claim.expected else 'refuted')
            except Exception:
                row['status'] = 'check-error'
        rows.append(row)
    return {'claims': rows, 'review_required': any(row['status'] != 'observed-match' for row in rows),
            'scope': 'Named callback observations only; no task completion or promotion.'}
