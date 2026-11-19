"""Offline whole-prefix RDAP service planning from bounded supplied IANA data."""
from collections import defaultdict
from datetime import datetime, timezone
import heapq
import ipaddress
import json
import re

from .client import GeofeedError
from .feed import digest, public
from .local_output import read_output
from .registry_check import _unique_json, _invalid_constant
from .registry_rdap import _finite_float

MAX_BYTES = 1_000_000
MAX_SERVICES = 100
MAX_PREFIXES = 4096
MAX_URLS = 8
SERVICE_BASES = frozenset((
    'https://rdap.afrinic.net/rdap/', 'https://rdap.apnic.net/',
    'https://rdap.arin.net/registry/', 'https://rdap.db.ripe.net/',
    'https://rdap.lacnic.net/rdap/',
))
_UTC = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|\+00:00)')


def _timestamp(value, now):
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise ValueError()
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp > now:
        raise ValueError()
    return stamp


def _network(value, version=None):
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or '/' not in value or '%' in value:
        raise ValueError()
    net = ipaddress.ip_network(value, strict=True)
    if str(net) != value or (version is not None and net.version != version):
        raise ValueError()
    return net


def _service(urls):
    if (not isinstance(urls, list) or not 1 <= len(urls) <= MAX_URLS
            or any(not isinstance(url, str) or not 1 <= len(url) <= 256 for url in urls)
            or len(set(urls)) != len(urls)):
        raise ValueError()
    secure = [url for url in urls if url.startswith('https://')]
    if len(secure) != 1:
        raise GeofeedError('Bootstrap service alternatives are unsupported or ambiguous; no URL selected')
    base = secure[0]
    if base not in SERVICE_BASES:
        raise GeofeedError('Bootstrap service base is not supported by this initial RIR profile; no URL selected')
    if any(url not in (base, base.replace('https://', 'http://', 1)) for url in urls):
        raise GeofeedError('Bootstrap service alternatives are unsupported or ambiguous; no URL selected')
    return base


def _select(routes, requested):
    """Sweep clipped boundaries, applying longest-prefix choice at every interval."""
    start, stop = int(requested.network_address), int(requested.broadcast_address) + 1
    events = defaultdict(list)
    events[start]; events[stop]
    for index, (net, _) in enumerate(routes):
        left, right = max(start, int(net.network_address)), min(stop, int(net.broadcast_address) + 1)
        if left < right:
            events[left].append((1, index)); events[right].append((-1, index))
    active, heap, selected, used, previous = set(), [], set(), set(), None
    for point in sorted(events):
        if previous is not None and previous < point:
            while heap and heap[0][1] not in active:
                heapq.heappop(heap)
            if not heap:
                raise GeofeedError('Supplied bootstrap does not cover the entire requested prefix; no URL selected')
            winner = heap[0][1]
            selected.add(routes[winner][1]); used.add(winner)
        for direction, index in events[point]:
            if direction == 1:
                active.add(index)
                heapq.heappush(heap, (-routes[index][0].prefixlen, index))
            else:
                active.remove(index)
        previous = point
    if len(selected) != 1:
        raise GeofeedError('Requested prefix spans multiple bootstrap services; use a narrower explicit scope, no URL selected')
    return sorted(selected)[0], len(used)


def plan_bootstrap(data, prefix, observed_at, *, now=None):
    """This plans a URL. It never verifies origin, performs a lookup or publishes."""
    current = datetime.now(timezone.utc) if now is None else now
    try:
        requested = _network(prefix)
        if not public(requested):
            raise GeofeedError('RDAP planning requires a public prefix outside static special-use ranges; no URL selected')
        stamp = _timestamp(observed_at, current)
        if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_BYTES:
            raise ValueError()
        source = json.loads(data, object_pairs_hook=_unique_json, parse_constant=_invalid_constant,
                            parse_float=_finite_float)
        if not isinstance(source, dict) or source.get('version') != '1.0':
            raise ValueError()
        publication = _timestamp(source.get('publication'), current)
        if publication > stamp:
            raise ValueError()
        services = source.get('services')
        if not isinstance(services, list) or not 1 <= len(services) <= MAX_SERVICES:
            raise ValueError()
        routes, seen = [], set()
        for service in services:
            if not isinstance(service, list) or len(service) != 2:
                raise ValueError()
            prefixes, urls = service
            if not isinstance(prefixes, list) or not 1 <= len(prefixes) <= MAX_PREFIXES:
                raise ValueError()
            base = _service(urls)
            for value in prefixes:
                net = _network(value, requested.version)
                if net in seen:
                    raise GeofeedError('Supplied bootstrap repeats a prefix; equal-scope resolution is unsupported, no URL selected')
                seen.add(net); routes.append((net, base))
                if len(routes) > MAX_PREFIXES:
                    raise ValueError()
        base, matched = _select(routes, requested)
        return {'inspection_only': True, 'planning_only': True, 'requested_prefix': str(requested),
                'address_family': requested.version, 'rdap_base_url': base,
                'rdap_lookup_url': base + 'ip/' + str(requested),
                'bootstrap_source': 'operator_supplied_iana_bootstrap', 'bootstrap_version': '1.0',
                'bootstrap_sha256': digest(data), 'bootstrap_prefix_count': len(routes),
                'bootstrap_matched_scope_count': matched,
                'bootstrap_match': 'single_service_for_entire_prefix',
                'observed_at': current.isoformat(), 'bootstrap_observed_at': stamp.isoformat(),
                'bootstrap_observed_at_source': 'operator_supplied',
                'bootstrap_snapshot_age_seconds': int((current - stamp).total_seconds()),
                'bootstrap_publication': publication.isoformat(),
                'bootstrap_publication_age_seconds': int((current - publication).total_seconds()),
                'bootstrap_authenticity': 'not_measured', 'live_registry_read': 'not_measured',
                'ownership_validation': 'not_measured', 'current_allocation_validation': 'not_measured',
                'signature_validation': 'not_measured', 'public_retrieval': 'not_measured',
                'provider_ingestion': 'not_measured'}
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise GeofeedError('RDAP planning needs a bounded version-1.0 address bootstrap, canonical same-family prefixes and consistent actual UTC dates; malformed or unsupported input refused without logging values') from None


def plan_file(path, prefix, observed_at):
    snapshot = read_output(path, MAX_BYTES)
    if snapshot.identity is None:
        raise GeofeedError('RDAP planning requires an existing bounded regular bootstrap file')
    return plan_bootstrap(snapshot.data, prefix, observed_at)
