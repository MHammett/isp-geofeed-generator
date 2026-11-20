"""Initial offline reader for saved RIPE REST address-object JSON responses."""
import ipaddress
import json
import math
import re

from .client import GeofeedError
from .feed import digest
from .registry_check import MAX_OBJECTS, _invalid_constant, _scope, _unique_json


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError()
    return result


def _attributes(value):
    if not isinstance(value, dict) or not isinstance(value.get('attribute'), list) or not 1 <= len(value['attribute']) <= 200:
        raise ValueError()
    result = {}
    for item in value['attribute']:
        if (not isinstance(item, dict) or not isinstance(item.get('name'), str)
                or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', item['name'])
                or not isinstance(item.get('value'), str) or len(item['value']) > 8192
                or any(ord(c) < 32 or ord(c) == 127 for c in item['value'])):
            raise ValueError()
        result.setdefault(item['name'], []).append(item['value'])
    return result


def _one(values, name):
    if len(values.get(name, [])) != 1:
        raise ValueError()
    return values[name][0]


def _address_scope(kind, value):
    if kind == 'inetnum':
        match = re.fullmatch(r'([0-9.]{7,15}) *- *([0-9.]{7,15})', value)
        if match is None:
            raise ValueError()
        start, end = (ipaddress.IPv4Address(part) for part in match.groups())
        if int(start) > int(end):
            raise ValueError()
        return {'start': str(start), 'end': str(end)}
    network = ipaddress.IPv6Network(value, strict=True)
    if str(network) != value or '%' in value:
        raise ValueError()
    return {'prefix': str(network)}


def normalize_ripe(data, observed_at):
    """Keep exact scopes and reference values; never follow response links."""
    if not isinstance(data, bytes) or len(data) > 8_000_000:
        raise GeofeedError('Saved RIPE JSON exceeds the supported input limit')
    if not isinstance(observed_at, str):
        raise GeofeedError('Saved RIPE JSON requires its actual observation date; no registry read was made')
    try:
        source = json.loads(data, object_pairs_hook=_unique_json, parse_constant=_invalid_constant,
                            parse_float=_finite_float)
        if not isinstance(source, dict):
            raise ValueError()
        messages = source.get('errormessages', {})
        if messages not in ({}, {'errormessage': []}):
            raise ValueError()
        container = source.get('objects')
        if not isinstance(container, dict) or not isinstance(container.get('object'), list):
            raise ValueError()
        objects = container['object']
        if not 1 <= len(objects) <= MAX_OBJECTS:
            raise ValueError()
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise GeofeedError('Invalid or empty RIPE REST JSON, unsupported count, or API messages present; values are not logged') from None
    rows, ids = [], set()
    for index, obj in enumerate(objects, 1):
        try:
            if not isinstance(obj, dict) or obj.get('type') not in ('inetnum', 'inet6num'):
                raise ValueError()
            kind = obj['type']
            origin = obj.get('source')
            if not isinstance(origin, dict) or not isinstance(origin.get('id'), str):
                raise ValueError()
            source = origin['id'].upper()
            if source != 'RIPE':
                raise ValueError()
            attributes = _attributes(obj.get('attributes'))
            if _one(attributes, 'source').upper() != source or ({'inetnum', 'inet6num'} - {kind}) & attributes.keys():
                raise ValueError()
            scope = _address_scope(kind, _one(attributes, kind))
            key = _attributes(obj.get('primary-key'))
            if set(key) != {kind}:
                raise ValueError()
            key_scope = _address_scope(kind, _one(key, kind))
            if key_scope != scope:
                raise ValueError()
            identity = 'ripe:' + kind + ':' + digest(json.dumps(scope, sort_keys=True).encode())
            if identity in ids:
                raise ValueError()
            ids.add(identity)
            row = {'id': identity, **scope}
            _scope(row, identity)  # Share normalized scope validation, including exact family bounds.
            if 'geofeed' in attributes:
                row['geofeed'] = _one(attributes, 'geofeed')
            if 'remarks' in attributes:
                row['remarks'] = attributes['remarks']
            rows.append(row)
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, GeofeedError):
            raise GeofeedError(f'RIPE object {index} needs a unique RIPE inetnum/inet6num scope with matching primary key and supported single-line attributes; values are not logged') from None
    return json.dumps({'schema_version': 1, 'observed_at': observed_at, 'objects': rows},
                      ensure_ascii=True, separators=(',', ':')).encode()
