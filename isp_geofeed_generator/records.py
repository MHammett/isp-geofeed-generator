"""Canonical rich-location JSON and checked local record publication."""
import ipaddress
import json
from pathlib import Path
from .client import GeofeedError
from .feed import public, coverage_guard
from .locations import validate_location
from .publish import atomic_write


def parse_records(data):
    try:
        if not data or len(data) > 8_000_000:
            raise ValueError()
        document = json.loads(data)
        if set(document) != {'schema_version', 'records'} or type(document['schema_version']) is not int or document['schema_version'] != 1:
            raise ValueError()
        rows = document['records']
        if not isinstance(rows, list) or not rows:
            raise ValueError()
        nets = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {'prefix', 'location'}:
                raise ValueError()
            net = ipaddress.ip_network(row['prefix'], strict=True)
            if not public(net) or str(net) != row['prefix']:
                raise ValueError()
            validate_location(row['location'], set(row['location']))
            nets.append(net)
        nets.sort(key=lambda n: (n.version, int(n.network_address)))
        if any(a.version == b.version and a.overlaps(b) for a, b in zip(nets, nets[1:])):
            raise ValueError()
        return rows, nets
    except (TypeError, KeyError, ValueError, UnicodeError):
        raise GeofeedError('Invalid normalized geolocation record document') from None


def encode_records(records):
    value = json.dumps({'schema_version': 1, 'records': records}, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':')).encode() + b'\n'
    parse_records(value)
    return value


def publish_records_file(path, records, state_dir, *, max_removed_fraction=0.10, max_relocated_fraction=0.10):
    from .relocation import relocation_guard
    value = encode_records(records)
    _, after = parse_records(value)
    target = Path(path)
    old = target.read_bytes() if target.exists() else b''
    if old:
        old_records, before = parse_records(old)
    else:
        old_records, before = [], []
    coverage_guard(before, after, max_removed_fraction)
    relocation_guard(old_records, records, max_relocated_fraction)
    atomic_write(Path(state_dir)/'before-records.json', old)
    if old != value:
        atomic_write(target, value, 0o644)
    if target.read_bytes() != value:
        atomic_write(target, old, 0o644)
        raise GeofeedError('Record-file read-back failed; restored previous bytes')
    from .feed import digest
    return {'changed': old != value, 'sha256': digest(value), 'path': str(target), 'format': 'location-records-v1'}
