"""Read-only public delivery observations, separate from publication health."""
from datetime import datetime, timezone

from .client import GeofeedError
from .feed import digest


def inspect_delivery(client, *, probe_cache=False):
    if probe_cache and not callable(getattr(client, 'read_public_probe', None)):
        raise GeofeedError('Selected client lacks the read-only public cache probe; update the client')
    before = client.policy_state()

    def observe(read):
        try:
            return read(overlap_policy=before.policy)
        except GeofeedError:
            # Remote bodies, headers, URLs and exception text are not diagnostics.
            # None is not measured; a real 404 is the existing empty-feed result.
            return None

    public = observe(client.read_public)
    probe = observe(client.read_public_probe) if probe_cache else None
    try:
        after = client.policy_state()
    except GeofeedError:
        after = None
    stable = before == after if after is not None else None
    matches = public == before.csv if public is not None else None
    probe_matches = probe == before.csv if probe is not None else None
    if stable is None:
        finding = 'state_recheck_unavailable'
    elif not stable:
        finding = 'state_changed'
    elif public is None:
        finding = 'canonical_unavailable_probe_matches' if probe_matches else 'public_read_unavailable'
    elif matches:
        finding = ('canonical_matches' if not probe_cache else 'probe_unavailable' if probe is None
                   else 'both_match' if probe_matches else 'probe_differs')
    elif not probe_cache:
        finding = 'canonical_differs'
    elif probe is None:
        finding = 'canonical_differs_probe_unavailable'
    elif probe_matches:
        finding = 'canonical_differs_probe_matches'
    else:
        finding = 'both_differ_same_bytes' if public == probe else 'both_differ_different_bytes'
    return {
        'inspection_only': True, 'observed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'feed_present': bool(before.csv), 'url': client.public_url, 'sha256': digest(before.csv),
        'overlap_policy': before.policy, 'required_overlap_policy': before.required,
        'publication_id': before.publication_id, 'previous_sha256': digest(before.previous),
        'previous_overlap_policy': before.previous_policy,
        'public_read_measured': public is not None, 'public_sha256': digest(public) if public is not None else None,
        'public_matches_stored': matches, 'policy_state_stable': stable,
        'cache_probe_requested': probe_cache, 'cache_probe_measured': probe is not None,
        'cache_probe_sha256': digest(probe) if probe is not None else None,
        'cache_probe_matches_stored': probe_matches, 'delivery_finding': finding,
        'inspection_consistent': finding in ('canonical_matches', 'both_match'),
    }
