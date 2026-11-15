"""Named, required inputs. Union inventories without implicit joins or precedence."""
import ipaddress
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from .client import GeofeedError, https_url
from .credentials import InputCredentialStore
from .feed import build_records

POLICIES = {'pool_sites', 'exclude_pools', 'site_locations'}


def validate_source(source, registry):
    if not isinstance(source, dict) or not isinstance(source.get('type'), str) or source['type'] not in registry:
        raise GeofeedError('Choose source.type from: ' + ', '.join(sorted(registry)))
    adapter = registry[source['type']]
    if set(source) - ({'type', 'allow_initial'} | adapter.settings):
        raise GeofeedError('Unknown source configuration keys')
    if 'allow_initial' in source and type(source['allow_initial']) is not bool:
        raise GeofeedError('source.allow_initial must be true or false')
    if adapter.validate is not None:
        adapter.validate(source)


def validate_inputs(config, registry, parent):
    entries = config['inputs']
    if 'source' in config or any(config.get(key) for key in POLICIES):
        raise GeofeedError('Use either source or inputs; put pool/site mappings and exclusions inside each named input')
    if not isinstance(entries, dict) or not 1 <= len(entries) <= 32:
        raise GeofeedError('inputs must contain 1 to 32 named required inputs')
    for name, entry in entries.items():
        if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', name):
            raise GeofeedError('Input names must be short lowercase names using letters, digits, underscores or hyphens')
        if not isinstance(entry, dict) or set(entry) - ({'source', 'url', 'credentials'} | POLICIES):
            raise GeofeedError(f'Input {name} has invalid or unknown configuration keys')
        validate_source(entry.get('source'), registry)
        source = entry['source']
        if source['type'] == 'sonar' and 'pool_ids' not in source:
            raise GeofeedError(f'Input {name}: explicitly select Sonar pool_ids, or use [] for subnet-only reads')
        for key in POLICIES:
            if not isinstance(entry.get(key, {}), dict):
                raise GeofeedError(f'Input {name}: {key} must be a mapping')
        url = entry.get('url')
        if url is not None:
            if not isinstance(url, str):
                raise GeofeedError(f'Input {name}: URL must be a string')
            parts = urlsplit(url)
            if source['type'] == 'netbox' and source.get('allow_http') is True and parts.scheme == 'http':
                if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
                    raise GeofeedError(f'Input {name}: invalid NetBox URL')
            else:
                https_url(url)
        InputCredentialStore(entry.get('credentials', {}), parent, url)


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def read_inputs(config, parent, command, *, assignments=False, controllers=False):
    if (assignments or controllers) and not any(e['source']['type'] == 'sonar' for e in config['inputs'].values()):
        raise GeofeedError('Sonar discovery flags need at least one Sonar input')
    results = {}
    for name, entry in config['inputs'].items():
        kind = entry['source']['type']
        try:
            credentials = InputCredentialStore(entry.get('credentials', {}), parent, entry.get('url'))
            adapter = config.sources[kind]
            started = timestamp()
            source = adapter.create(entry['source'], credentials)
            snapshot = source.snapshot()
            if command == 'discover':
                if kind == 'sonar' and assignments:
                    snapshot['assignment_candidates'] = source.assignment_candidates(snapshot['sites'])
                    snapshot['candidate_warning'] = 'Observed address use is not proof of pool hosting or ownership. Review before mapping.'
                if kind == 'sonar' and controllers:
                    snapshot['controller_candidates'] = source.controller_candidates(snapshot)
            else:
                snapshot = source.for_publication(snapshot)
                if command == 'publish' and adapter.initial and entry['source'].get('allow_initial') is not True:
                    raise GeofeedError('Initial adapter: test discovery/candidates and set this input source.allow_initial: true before publishing')
            results[name] = {'source_type': kind, 'read_started_at': started, 'read_completed_at': timestamp(), 'snapshot': snapshot}
        except GeofeedError as exc:
            raise GeofeedError(f'Input {name} ({kind}): {parent.redact(str(exc))}') from None
        except Exception as exc:
            raise GeofeedError(f'Input {name} ({kind}) was not measured ({type(exc).__name__}); no partial feed accepted') from None
    return results


def combine_inputs(results, config, fields):
    entries, report = [], []
    for name, result in results.items():
        try:
            snapshot = result['snapshot']
            policy = {'allowed_prefixes': config.get('allowed_prefixes', []),
                      **{key: config['inputs'][name].get(key, {}) for key in POLICIES}}
            records, rows = build_records(snapshot, policy, fields)
            source_rows = {str(row['id']): row for row in snapshot['pools']}
            origins = {}
            for row in rows:
                origin = {**row, 'input': name, 'source_type': result['source_type'],
                          'source_record_id': source_rows[row['pool_id']].get('source_id', row['pool_id'])}
                candidate = snapshot.get('controller_candidates', {}).get(row['pool_id'])
                if candidate is not None:
                    origin['site_evidence'] = candidate
                report.append(origin)
                for cidr in row.get('cidrs', []):
                    origins[cidr] = origin
            for record in records:
                entries.append((ipaddress.ip_network(record['prefix']), record, origins[record['prefix']]))
        except GeofeedError as exc:
            raise GeofeedError(f'Input {name}: {exc}') from None
    entries.sort(key=lambda row: (row[0].version, int(row[0].network_address), row[0].prefixlen))
    for previous, current in zip(entries, entries[1:]):
        if previous[0].version == current[0].version and previous[0].overlaps(current[0]):
            left, right = previous[2], current[2]
            detail = 'conflicting locations' if previous[1]['location'] != current[1]['location'] else 'duplicate/overlapping coverage'
            raise GeofeedError(f"Combined input {detail}: {left['input']}/{left['pool_id']} and {right['input']}/{right['pool_id']}; no precedence was applied")
    if not entries:
        raise GeofeedError('No combined public records; refusing an empty feed')
    return [row[1] for row in entries], report
