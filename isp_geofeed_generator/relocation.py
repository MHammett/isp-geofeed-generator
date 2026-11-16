"""Compare published location fields by exact retained address intersections."""
import ipaddress
import unicodedata
from fractions import Fraction
from .client import GeofeedError
from .locations import validate_location


def location_intervals(records):
    rows = []
    try:
        for record in records:
            net = ipaddress.ip_network(record['prefix'], strict=True)
            location = validate_location(record['location'], set(record['location']))
            signature = tuple((key, unicodedata.normalize('NFC', value) if isinstance(value, str) else value)
                              for key, value in sorted(location.items()))
            rows.append((net, signature))
        rows.sort(key=lambda row: (row[0].version, int(row[0].network_address), row[0].prefixlen))
        if any(a[0].version == b[0].version and a[0].overlaps(b[0]) for a, b in zip(rows, rows[1:])):
            raise GeofeedError('Location comparison requires nonoverlapping records')
        return rows
    except (KeyError, TypeError, ValueError):
        raise GeofeedError('Invalid location comparison records') from None


def relocation_guard(old, new, max_relocated_fraction=0.10):
    limit = max_relocated_fraction
    if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not 0 <= limit <= 1:
        raise GeofeedError('max_relocated_fraction must be between 0 and 1')
    threshold = Fraction(str(limit))
    before, after = location_intervals(old), location_intervals(new)
    for version in (4, 6):
        left = [(net, loc) for net, loc in before if net.version == version]
        right = [(net, loc) for net, loc in after if net.version == version]
        retained = moved = i = j = 0
        while i < len(left) and j < len(right):
            a, a_location = left[i]; b, b_location = right[j]
            start = max(int(a.network_address), int(b.network_address))
            end = min(int(a.broadcast_address), int(b.broadcast_address))
            overlap = max(0, end - start + 1)
            retained += overlap
            if a_location != b_location:
                moved += overlap
            if int(a.broadcast_address) < int(b.broadcast_address):
                i += 1
            else:
                j += 1
        if retained and moved * threshold.denominator > retained * threshold.numerator:
            raise GeofeedError(f'IPv{version} location changes affect {moved} of {retained} retained addresses; '
                               f'max_relocated_fraction={limit}; output stopped. Review a generated candidate before approving its exact hash')
