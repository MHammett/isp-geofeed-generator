"""Bounded offline composition of explicitly supplied registry response files."""
from datetime import datetime, timezone
import json

from .client import GeofeedError
from .feed import digest
from .local_output import read_output
from .overlap import REJECT
from .registry_check import MAX_OBJECTS, _load_snapshot, check_files, check_snapshot

MAX_FILES = 32
MAX_BYTES = 8_000_000


def _encode(value):
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode()


def check_file_set(paths, feed_path, expected_url, *, overlap_policy=REJECT, input_format='normalized', observed_at=None):
    """Every file and date participates. A refusal never becomes a partial report."""
    if not isinstance(paths, (list, tuple)) or not 1 <= len(paths) <= MAX_FILES:
        raise GeofeedError('Registry comparison requires 1 to 32 explicitly supplied input files')
    if input_format not in ('normalized', 'ripe-rest'):
        raise GeofeedError('Registry input format must be normalized or ripe-rest')
    if input_format == 'normalized':
        if observed_at is not None:
            raise GeofeedError('Normalized registry inputs use their embedded dates; a separate observation date is refused')
        dates = [None] * len(paths)
    else:
        if (not isinstance(observed_at, (list, tuple)) or len(observed_at) != len(paths)
                or any(not isinstance(stamp, str) for stamp in observed_at)):
            raise GeofeedError('Saved RIPE inputs require one --registry-observed-at per --registry-records, in the same order')
        dates = observed_at
    if len(paths) == 1:
        # Preserve the existing single-file API/report, including the raw-file hash.
        return check_files(paths[0], feed_path, expected_url, overlap_policy=overlap_policy,
                           input_format=input_format, observed_at=dates[0])

    now = datetime.now(timezone.utc)
    remaining, total_objects, rows, inputs, stamps = MAX_BYTES, 0, [], [], []
    for index, path in enumerate(paths, 1):
        try:
            snapshot = read_output(path, remaining)
            if snapshot.identity is None:
                raise GeofeedError('Registry input must be an existing bounded regular file')
            remaining -= len(snapshot.data)
            data = snapshot.data
            if input_format == 'ripe-rest':
                from .registry_ripe import normalize_ripe
                data = normalize_ripe(data, dates[index - 1])
            source, stamp = _load_snapshot(data, now)
            total_objects += len(source['objects'])
            if total_objects > MAX_OBJECTS:
                raise GeofeedError('Combined registry inputs exceed the supported object limit')
            rows.extend(source['objects'])
            stamps.append(stamp)
            inputs.append({'input': index, 'snapshot_sha256': digest(snapshot.data),
                           'normalized_snapshot_sha256': digest(data),
                           'snapshot_observed_at': stamp.isoformat(timespec='seconds'),
                           'snapshot_age_seconds': int((now - stamp).total_seconds()),
                           'snapshot_observed_at_source': 'operator_supplied',
                           'registry_objects': len(source['objects'])})
        except GeofeedError as exc:
            raise GeofeedError(f'Registry input {index}: {exc}; no partial comparison made') from None

    data = _encode({'schema_version': 1, 'observed_at': min(stamps).isoformat(timespec='seconds'), 'objects': rows})
    if len(data) > MAX_BYTES:
        raise GeofeedError('Combined normalized registry inputs exceed the supported byte limit')
    feed = read_output(feed_path, 1_000_000)
    if feed.identity is None:
        raise GeofeedError('Feed must be an existing bounded regular file')
    # One final comparison rejects duplicate IDs and crossing scopes across files.
    # Never drop a later file, pick a newer version, or silently deduplicate objects.
    result = check_snapshot(data, feed.data, expected_url, overlap_policy=overlap_policy, now=now)
    result.update(registry_input_format=input_format, snapshot_input_count=len(inputs), snapshot_inputs=inputs,
                  normalized_snapshot_sha256=digest(data), snapshot_sha256_scope='combined_normalized_snapshot',
                  source_manifest_sha256=digest(_encode([{key: value for key, value in item.items()
                                                         if key != 'snapshot_age_seconds'} for item in inputs])),
                  snapshot_observed_at_basis='oldest_supplied_input',
                  snapshot_observed_at_source='operator_supplied')
    if input_format == 'ripe-rest':
        result['registry_source'] = 'RIPE'
    return result
