"""Offline unsigned-feed discovery checks against bounded supplied registry scopes."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import heapq
import ipaddress
import json
import re
from urllib.parse import urlsplit

from .client import GeofeedError
from .feed import digest, parse_feed
from .local_output import read_output
from .overlap import REJECT

MAX_OBJECTS = 50_000
MAX_DETAILS = 1_000
KINDS = ('this_feed', 'other_feed', 'unreferenced', 'invalid_reference', 'ambiguous_reference')


@dataclass(frozen=True)
class _Scope:
    version: int
    start: int
    end: int  # Inclusive. Preserve the original object rather than splitting into CIDRs.


def _scope(row, identity):
    try:
        if 'prefix' in row and not {'start', 'end'} & row.keys():
            prefix = row['prefix']
            if not isinstance(prefix, str) or not 1 <= len(prefix) <= 128 or '%' in prefix:
                raise ValueError()
            net = ipaddress.ip_network(prefix, strict=True)
            if str(net) != prefix:
                raise ValueError()
            return _Scope(net.version, int(net.network_address), int(net.broadcast_address))
        if 'prefix' not in row and {'start', 'end'} <= row.keys():
            values = (row['start'], row['end'])
            if any(not isinstance(value, str) or not 1 <= len(value) <= 45 or '%' in value for value in values):
                raise ValueError()
            start, end = (ipaddress.ip_address(value) for value in values)
            if (start.version != end.version or int(start) > int(end)
                    or str(start) != values[0] or str(end) != values[1]):
                raise ValueError()
            return _Scope(start.version, int(start), int(end))
        raise ValueError()
    except (ValueError, TypeError):
        raise GeofeedError(f'Registry object {identity} needs either a canonical CIDR prefix or inclusive canonical start/end addresses of one family') from None


def _check_hierarchy(references):
    """Containment gives one most-specific scope. Crossing ranges have no such order."""
    stack = []
    for reference in sorted(references, key=lambda value: (value[0].version, value[0].start, -value[0].end)):
        scope = reference[0]
        while stack and (scope.version != stack[-1][0].version or scope.start > stack[-1][0].end):
            stack.pop()
        if stack and scope.end > stack[-1][0].end:
            raise GeofeedError(f'Registry objects {stack[-1][2][0]} and {reference[2][0]} have crossing referring scopes; containment order is unsupported, no comparison made')
        stack.append(reference)


def feed_url(value):
    """A bounded ASCII HTTPS URL; never fetched. Queries and fragments are retained."""
    if (not isinstance(value, str) or not 1 <= len(value) <= 2048
            or any(ord(c) <= 32 or ord(c) >= 127 or c in '<>"{}|\\^`' for c in value)
            or re.search(r'%(?![0-9a-fA-F]{2})', value)):
        return False
    try:
        parts = urlsplit(value)
        return bool(parts.scheme == 'https' and parts.hostname and parts.username is None and parts.password is None
                    and (parts.port is None or 1 <= parts.port <= 65535))
    except ValueError:
        return False


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _invalid_constant(_):
    raise ValueError('non-JSON constant')


def check_snapshot(data, csv, expected_url, *, overlap_policy=REJECT, now=None):
    if not feed_url(expected_url):
        raise GeofeedError('Expected feed URL must be a bounded HTTPS URL without credentials; no URL was fetched')
    if not isinstance(data, bytes) or len(data) > 8_000_000:
        raise GeofeedError('Registry snapshot exceeds the supported input limit')
    if not isinstance(csv, bytes):
        raise GeofeedError('Registry comparison requires CSV bytes')
    now = datetime.now(timezone.utc) if now is None else now
    try:
        source = json.loads(data, object_pairs_hook=_unique_json, parse_constant=_invalid_constant)
        if (not isinstance(source, dict) or set(source) != {'schema_version', 'observed_at', 'objects'}
                or type(source['schema_version']) is not int or source['schema_version'] != 1
                or not isinstance(source['objects'], list) or len(source['objects']) > MAX_OBJECTS
                or not isinstance(source['observed_at'], str)
                or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:Z|\+00:00)', source['observed_at'])):
            raise ValueError()
        stamp = datetime.fromisoformat(source['observed_at'].replace('Z', '+00:00'))
        if stamp > now:
            raise ValueError()
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise GeofeedError('Invalid registry snapshot schema, date or duplicate key; input values are not logged') from None
    networks = parse_feed(csv, overlap_policy=overlap_policy)
    if len(networks) > MAX_OBJECTS:
        raise GeofeedError('Registry comparison exceeds the supported feed record limit')
    findings, finding_count, groups, ids = [], 0, defaultdict(list), set()
    precedence = 0
    formats = {'cidr': 0, 'address_range': 0}

    def finding(kind, object_ids):
        nonlocal finding_count
        finding_count += 1
        if len(findings) < MAX_DETAILS:
            findings.append({'kind': kind, 'object_ids': object_ids[:4], 'object_count': len(object_ids)})

    for row in source['objects']:
        if (not isinstance(row, dict) or set(row) - {'id', 'prefix', 'start', 'end', 'geofeed', 'remarks'}
                or not isinstance(row.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', row['id'])
                or row['id'] in ids):
            raise GeofeedError('Registry objects need unique safe IDs and supported unsigned scope fields')
        identity = row['id']; ids.add(identity)
        scope = _scope(row, identity)
        formats['cidr' if 'prefix' in row else 'address_range'] += 1
        remarks = row.get('remarks', [])
        if (not isinstance(remarks, list) or len(remarks) > 20
                or any(not isinstance(item, str) or len(item) > 2048
                       or any(ord(c) < 32 or ord(c) == 127 for c in item) for item in remarks)):
            raise GeofeedError(f'Registry object {identity} has an unsupported remarks container')
        if 'geofeed' in row:
            # RFC 9632: native form takes precedence, including over another URL.
            precedence += bool(any(re.match(r'geofeed\b', item, re.I) for item in remarks))
            url = row['geofeed']
            kind = 'this_feed' if feed_url(url) and url == expected_url else 'other_feed' if feed_url(url) else 'invalid_reference'
            if kind == 'invalid_reference':
                finding('invalid_native_reference', [identity])
        else:
            candidates = [item for item in remarks if re.match(r'geofeed\b', item, re.I)]
            if not candidates:
                continue  # Objects without a reference do not shadow a parent reference.
            if len(candidates) > 1:
                kind = 'ambiguous_reference'; finding('multiple_remarks_references_unsupported', [identity])
            elif not candidates[0].startswith('Geofeed ') or not feed_url(candidates[0][8:]):
                kind = 'invalid_reference'; finding('invalid_remarks_reference', [identity])
            else:
                kind = 'this_feed' if candidates[0][8:] == expected_url else 'other_feed'
        groups[scope].append((identity, kind))

    references = []
    for scope, rows in groups.items():
        if len(rows) > 1:
            finding('same_scope_resolution_unsupported', [row[0] for row in rows])
            kind = 'ambiguous_reference'
        else:
            kind = rows[0][1]
        references.append((scope, kind, [row[0] for row in rows]))
    _check_hierarchy(references)

    coverage, details, interval_count = {}, [], 0
    for version in (4, 6):
        events = defaultdict(list)
        for net in networks:
            if net.version == version:
                events[int(net.network_address)].append(('feed', 1, 0))
                events[int(net.broadcast_address) + 1].append(('feed', -1, 0))
        for index, (scope, _, _) in enumerate(references):
            if scope.version == version:
                events[scope.start].append(('reference', 1, index))
                events[scope.end + 1].append(('reference', -1, index))
        counts = {kind: 0 for kind in KINDS}
        active, heap, feeds, previous = set(), [], 0, None
        for point in sorted(events):
            if previous is not None and point > previous and feeds:
                while heap and heap[0][1] not in active:
                    heapq.heappop(heap)
                selected = heap[0][1] if heap else None
                kind = references[selected][1] if selected is not None else 'unreferenced'
                counts[kind] += point - previous
                if kind != 'this_feed':
                    interval_count += 1
                    if len(details) < MAX_DETAILS:
                        address = ipaddress.IPv4Address if version == 4 else ipaddress.IPv6Address
                        objects = references[selected][2] if selected is not None else []
                        details.append({'family': version, 'start': str(address(previous)), 'end': str(address(point - 1)),
                                        'kind': kind, 'object_ids': objects[:4], 'object_count': len(objects)})
            for category, direction, index in events[point]:
                if category == 'feed':
                    feeds += direction
                elif direction == 1:
                    active.add(index)
                    scope = references[index][0]
                    heapq.heappush(heap, (scope.end - scope.start, index))
                else:
                    active.remove(index)
            previous = point
        coverage[str(version)] = {**{key: str(value) for key, value in counts.items()}, 'total': str(sum(counts.values()))}
    consistent = finding_count == 0 and all(values['this_feed'] == values['total'] for values in coverage.values())
    return {
        'inspection_only': True, 'comparison_consistent': consistent,
        'scope': 'supplied_unsigned_range_snapshot' if formats['address_range'] else 'supplied_unsigned_cidr_snapshot',
        'registry_scope_formats': formats, 'observed_at': now.isoformat(timespec='seconds'),
        'snapshot_observed_at': stamp.isoformat(timespec='seconds'), 'snapshot_age_seconds': int((now - stamp).total_seconds()),
        'live_registry_read': 'not_measured', 'ownership_validation': 'not_measured',
        'signature_validation': 'not_measured',
        'current_allocation_validation': 'not_measured', 'public_retrieval': 'not_measured', 'provider_ingestion': 'not_measured',
        'feed_sha256': digest(csv), 'feed_url_sha256': digest(expected_url.encode()), 'snapshot_sha256': digest(data),
        'overlap_policy': overlap_policy, 'feed_records': len(networks), 'registry_objects': len(ids),
        'native_precedence_objects': precedence, 'coverage': coverage,
        'finding_count': finding_count, 'findings': findings, 'coverage_interval_count': interval_count,
        'coverage_details': details, 'details_truncated': finding_count > len(findings) or interval_count > len(details),
    }


def check_files(snapshot_path, feed_path, expected_url, *, overlap_policy=REJECT):
    snapshot = read_output(snapshot_path, 8_000_000)
    feed = read_output(feed_path, 1_000_000)
    if snapshot.identity is None or feed.identity is None:
        raise GeofeedError('Registry snapshot and feed must both be existing bounded regular files')
    return check_snapshot(snapshot.data, feed.data, expected_url, overlap_policy=overlap_policy)
