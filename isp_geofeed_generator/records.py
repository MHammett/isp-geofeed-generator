"""Canonical rich-location JSON and checked local record publication."""
import ipaddress
import json
from pathlib import Path
from .client import GeofeedError
from .feed import public, coverage_guard
from .locations import validate_location
from .overlap import REJECT, LONGEST_PREFIX, validate_policy, validate_networks


def parse_records(data, *, overlap_policy=REJECT):
    validate_policy(overlap_policy)
    try:
        if not data or len(data) > 8_000_000:
            raise ValueError()
        document = json.loads(data)
        keys = {'schema_version', 'records'} | ({'overlap_policy'} if overlap_policy == LONGEST_PREFIX else set())
        version = 2 if overlap_policy == LONGEST_PREFIX else 1
        if (set(document) != keys or type(document['schema_version']) is not int or document['schema_version'] != version
                or (version == 2 and document['overlap_policy'] != LONGEST_PREFIX)):
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
        validate_networks(nets, overlap_policy)
        if overlap_policy == LONGEST_PREFIX:
            from ._effective import effective_intervals
            effective_intervals(rows, fields=frozenset(rows[0]['location']))
        return rows, nets
    except (TypeError, KeyError, ValueError, UnicodeError, GeofeedError):
        raise GeofeedError('Invalid normalized geolocation record document') from None


def encode_records(records, *, overlap_policy=REJECT):
    validate_policy(overlap_policy)
    document = {'schema_version': 2 if overlap_policy == LONGEST_PREFIX else 1, 'records': records}
    if overlap_policy == LONGEST_PREFIX:
        document['overlap_policy'] = overlap_policy
    value = json.dumps(document, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':')).encode() + b'\n'
    parse_records(value, overlap_policy=overlap_policy)
    return value


def publish_records_file(path, records, state_dir, *, max_removed_fraction=0.10, max_relocated_fraction=0.10, overlap_policy=REJECT):
    from .relocation import relocation_guard
    from .local_output import publish_local
    value = encode_records(records,overlap_policy=overlap_policy)
    if overlap_policy == LONGEST_PREFIX:
        from .bound_output import publish_bound
        from .relocation import effective_change_guard
        def validate_bound(old,candidate,old_policy):
            after_records,_=parse_records(candidate,overlap_policy=overlap_policy)
            old_records=parse_records(old,overlap_policy=old_policy)[0] if old else []
            effective_change_guard(old_records,after_records,max_removed_fraction,max_relocated_fraction,
                                   fields=frozenset(after_records[0]['location']))
        changed=publish_bound(path,value,state_dir,'records',validate_bound,8_000_000)
        from .feed import digest
        return {'changed':changed,'sha256':digest(value),'path':str(Path(path)),'format':'location-records-v2',
                'overlap_policy':overlap_policy,'verification':'local-bytes-and-policy','recovery_backup_changed':changed}
    def validate(old, candidate):
        after_records, after = parse_records(candidate)
        old_records, before = parse_records(old) if old else ([], [])
        coverage_guard(before, after, max_removed_fraction)
        relocation_guard(old_records, after_records, max_relocated_fraction)
    changed = publish_local(path, value, state_dir, 'before-records.json', validate, 8_000_000)
    from .feed import digest
    return {'changed': changed, 'sha256': digest(value), 'path': str(Path(path)), 'format': 'location-records-v1',
            'verification': 'local-bytes', 'recovery_backup_changed': changed}
