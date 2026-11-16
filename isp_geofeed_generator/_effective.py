"""Internal analysis for issue #16, not an overlap-enabled publication path.

Callers must still perform source, ownership, bogon and target-policy validation.
The active parsers/publishers continue to reject overlaps. This module computes
longest-prefix locations without enumerating addresses or flattening a feed.
"""
from dataclasses import dataclass
import heapq
import ipaddress
import unicodedata

from .client import GeofeedError
from .locations import COARSE_FIELDS, LOCATION_FIELDS, validate_location

MAX_RECORDS = 50_000


@dataclass(frozen=True, slots=True)
class Interval:
    version: int
    start: int
    stop: int  # Exclusive; IPv6's last endpoint can be 2**128.
    location: tuple
    record_index: int  # Private provenance in the caller's raw record sequence.


@dataclass(frozen=True, slots=True)
class CoverageChange:
    old: int
    new: int
    retained: int
    removed: int
    relocated: int

    def decimal_counts(self):
        """Safe JSON values; JavaScript must not round IPv6 address counts."""
        return {key: str(getattr(self, key)) for key in
                ('old', 'new', 'retained', 'removed', 'relocated')}


def effective_intervals(records, *, fields=COARSE_FIELDS):
    """Validate every raw location, then derive disjoint longest-prefix intervals.

    Exact duplicates are errors, even when locations match. Each winner supplies
    its entire requested location profile; fields are never inherited. Work and
    memory depend on records/events, never on the number of covered addresses.
    """
    if (not isinstance(fields, (set, frozenset)) or not fields or fields - LOCATION_FIELDS
            or ('latitude' in fields) != ('longitude' in fields)):
        raise GeofeedError('Invalid effective interval location profile')
    try:
        iterator = iter(records)
    except TypeError:
        raise GeofeedError('Invalid effective interval records') from None
    rows, events, seen = [], [], set()
    for index, record in enumerate(iterator):
        if index >= MAX_RECORDS:
            raise GeofeedError('Effective interval analysis exceeds record limit')
        try:
            if not isinstance(record['prefix'], str):
                raise ValueError()
            net = ipaddress.ip_network(record['prefix'], strict=True)
            if str(net) != record['prefix'] or '%' in record['prefix']:
                raise ValueError()
            values = record['location']
            if not isinstance(values, dict) or set(values) - fields:
                raise ValueError()
            location = validate_location(values, fields)
            signature = tuple((key, unicodedata.normalize('NFC', value) if isinstance(value, str) else value)
                              for key, value in sorted(location.items()))
        except (KeyError, TypeError, ValueError, GeofeedError):
            raise GeofeedError(f'Invalid effective interval record {index + 1}') from None
        if net in seen:
            raise GeofeedError(f'Duplicate effective interval prefix at record {index + 1}')
        seen.add(net)
        rows.append((net.prefixlen, signature))
        events.append((net.version, int(net.network_address), 1, index))
        events.append((net.version, int(net.broadcast_address) + 1, -1, index))

    events.sort()
    active, heap, result = set(), [], []
    previous = None
    position = 0
    while position < len(events):
        version, point = events[position][:2]
        if previous is not None and heap and point > previous:
            winner = heap[0][1]
            result.append(Interval(version, previous, point, rows[winner][1], winner))
        # At one boundary remove expired rows before adding new rows. Choose the
        # most specific remaining row only after all events at this point run.
        while position < len(events) and events[position][:2] == (version, point):
            _, _, direction, index = events[position]
            if direction < 0:
                active.remove(index)
            else:
                active.add(index)
                heapq.heappush(heap, (-rows[index][0], index))
            position += 1
        while heap and heap[0][1] not in active:
            heapq.heappop(heap)
        previous = point
    return tuple(result)


def compare_effective(before, after, *, fields=COARSE_FIELDS):
    """Exact per-family union, withdrawal and retained-location change counts.

    Added coverage is ``new - retained``; it is not a relocation baseline.
    """
    left, right = effective_intervals(before, fields=fields), effective_intervals(after, fields=fields)
    result = {}
    for version in (4, 6):
        old = [item for item in left if item.version == version]
        new = [item for item in right if item.version == version]
        old_size = sum(item.stop - item.start for item in old)
        new_size = sum(item.stop - item.start for item in new)
        retained = relocated = i = j = 0
        while i < len(old) and j < len(new):
            a, b = old[i], new[j]
            size = max(0, min(a.stop, b.stop) - max(a.start, b.start))
            retained += size
            if a.location != b.location:
                relocated += size
            if a.stop < b.stop:
                i += 1
            else:
                j += 1
        result[version] = CoverageChange(old_size, new_size, retained, old_size - retained, relocated)
    return result
