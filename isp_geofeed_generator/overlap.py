"""Explicit overlap policy, shared validation and target capability checks."""
from .client import GeofeedError
from ._effective import MAX_RECORDS

REJECT = 'reject'
LONGEST_PREFIX = 'longest_prefix'
OVERLAP_POLICIES = frozenset({REJECT, LONGEST_PREFIX})


def validate_policy(value):
    if not isinstance(value, str) or value not in OVERLAP_POLICIES:
        raise GeofeedError('overlap_policy must be reject or longest_prefix')
    return value


def validate_networks(networks, policy=REJECT):
    validate_policy(policy)
    rows = sorted(networks, key=lambda net: (net.version, int(net.network_address), net.prefixlen))
    if policy == LONGEST_PREFIX and len(rows) > MAX_RECORDS:
        raise GeofeedError('Nested-prefix policy exceeds record limit')
    seen = set()
    previous = None
    for net in rows:
        if net in seen or (policy == REJECT and previous is not None
                           and previous.version == net.version and previous.overlaps(net)):
            raise GeofeedError('Overlapping/duplicate prefixes are refused by the selected policy')
        seen.add(net)
        previous = net


def require_target_policy(adapter, policy):
    validate_policy(policy)
    version = getattr(adapter, 'api_version', 1)
    supported = getattr(adapter, 'overlap_policies', frozenset({REJECT}))
    if policy not in supported or (policy == LONGEST_PREFIX and version != 2):
        raise GeofeedError('Selected output does not support this overlap_policy; no write attempted')
