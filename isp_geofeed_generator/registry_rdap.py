"""Initial offline RDAP network reader; no bootstrap or linked-resource fetching."""
import ipaddress
import json
import math
from urllib.parse import urlsplit

from .client import GeofeedError
from .feed import digest
from .registry_check import _invalid_constant, _unique_json, feed_url


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError()
    return result


def _text(value, limit):
    return (isinstance(value, str) and 1 <= len(value) <= limit
            and not any(ord(c) < 32 or ord(c) == 127 for c in value))


def _complete(source):
    if 'errorCode' in source:
        raise GeofeedError('Saved RDAP is an error response; obtain a successful lookup before comparison; values are not logged')
    if 'redacted' in source:
        raise GeofeedError('Saved RDAP contains explicit redaction; redaction-path analysis is not supported by this reader; preserve the original reply, no comparison made')
    for key in ('notices', 'remarks'):
        messages = source.get(key, [])
        if not isinstance(messages, list) or len(messages) > 100:
            raise ValueError()
        for message in messages:
            if not isinstance(message, dict):
                raise ValueError()
            kind = message.get('type', '')
            if not isinstance(kind, str) or len(kind) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in kind):
                raise ValueError()
            if kind.lower().startswith(('result set truncated', 'object truncated')):
                raise GeofeedError('Saved RDAP reports truncation; no partial comparison made; preserve the original reply and inspect the export')


def _link(source):
    links = source.get('links', [])
    if not isinstance(links, list) or len(links) > 200:
        raise ValueError()
    references = []
    for link in links:
        if not isinstance(link, dict) or not _text(link.get('rel'), 128):
            raise ValueError()
        relations = link['rel'].lower().split()
        if not relations:
            raise ValueError()
        if 'geofeed' not in relations:
            continue  # Self, parent, contact and nested entity links are never fetched.
        context = link.get('value')
        if not _text(context, 2048):
            raise ValueError()
        parsed = urlsplit(context)
        if (parsed.scheme not in ('https', 'http') or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or (parsed.port is not None and not 1 <= parsed.port <= 65535)):
            raise ValueError()
        if not feed_url(link.get('href')):
            raise ValueError()
        if 'type' in link and (not _text(link['type'], 128) or link['type'].lower() != 'application/geofeed+csv'):
            raise ValueError()
        references.append(link['href'])
    if len(references) > 1:
        raise GeofeedError('Saved RDAP has multiple geofeed links; language/alternative selection is unsupported, no comparison made')
    return references[0] if references else None


def normalize_rdap(data, observed_at):
    """One saved lookup object becomes one exact unsigned scope and safe metadata."""
    if not isinstance(data, bytes) or len(data) > 8_000_000:
        raise GeofeedError('Saved RDAP JSON exceeds the supported input limit')
    if not isinstance(observed_at, str):
        raise GeofeedError('Saved RDAP requires its actual observation date; no registry read was made')
    try:
        source = json.loads(data, object_pairs_hook=_unique_json, parse_constant=_invalid_constant,
                            parse_float=_finite_float)
        if not isinstance(source, dict) or source.get('objectClassName') != 'ip network':
            raise ValueError()
        _complete(source)
        handle = source.get('handle')
        if not _text(handle, 256):
            raise ValueError()
        addresses = (source.get('startAddress'), source.get('endAddress'))
        if any(not _text(value, 45) or '%' in value for value in addresses):
            raise ValueError()
        start, end = (ipaddress.ip_address(value) for value in addresses)
        if start.version != end.version or int(start) > int(end) or source.get('ipVersion') != f'v{start.version}':
            raise ValueError()
        declarations = source.get('rdapConformance', [])
        if (not isinstance(declarations, list) or len(declarations) > 100
                or any(not _text(value, 128) for value in declarations) or len(set(declarations)) != len(declarations)):
            raise ValueError()
        reference = _link(source)
        scope = {'start': str(start), 'end': str(end)}
        identity = 'rdap:' + digest(json.dumps({'handle': handle, **scope}, sort_keys=True).encode())
        row = {'id': identity, **scope}
        if reference is not None:
            row['geofeed'] = reference
        advertised = 'geofeed1' in declarations
        metadata = {'registry_source': 'operator_supplied_rdap', 'rdap_geofeed1_advertised': advertised,
                    'rdap_link_status': 'link_returned' if reference is not None else
                        'not_returned_with_extension' if advertised else 'availability_not_measured'}
        normalized = json.dumps({'schema_version': 1, 'observed_at': observed_at, 'objects': [row]},
                                ensure_ascii=True, separators=(',', ':')).encode()
        return normalized, metadata
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise GeofeedError('Saved RDAP needs one complete ip network with a handle, matching IPv4/IPv6 bounds and supported geofeed links; errors, truncation/redaction or malformed values are refused without logging them') from None
