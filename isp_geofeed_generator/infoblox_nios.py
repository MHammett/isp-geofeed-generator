"""Initial read-only NIOS WAPI 2.13.6 networks with declared geography attributes."""
import base64
import hashlib
import ipaddress
import re
from urllib.parse import urlencode, urlsplit
from .client import GeofeedError, JsonHTTP, https_url

KINDS = ('network', 'ipv6network')
DEFAULT_FIELDS = {'country':'geofeed_country', 'region':'geofeed_region', 'city':'geofeed_city'}
MAX_PAGES = 10000
MAX_RECORDS = 50000


def native_ref(value, kind=None):
    if (not isinstance(value, str) or not 1 <= len(value) <= 2048
            or any(ord(c) < 33 or ord(c) > 126 for c in value)
            or value.split('/', 1)[0] not in ((kind,) if kind else KINDS)
            or '/' not in value or not value.split('/', 1)[1]):
        raise GeofeedError('NIOS returned a missing or invalid network reference')
    return value


def normalized_id(value):
    # References remain opaque. The digest keeps IDs bounded without decoding them.
    return 'network:' + hashlib.sha256(native_ref(value).encode('utf-8')).hexdigest()


def validate_settings(settings):
    refs = settings.get('network_refs', [])
    if not isinstance(refs, list) or len(refs) > 10000:
        raise GeofeedError('NIOS source.network_refs must be a bounded list of native references')
    for value in refs:
        native_ref(value)
    if len(refs) != len(set(refs)):
        raise GeofeedError('NIOS source.network_refs contains duplicate references')
    fields = settings.get('location_fields', {})
    if (not isinstance(fields, dict) or set(fields) - set(DEFAULT_FIELDS)
            or any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9 _.-]{0,127}', v) for v in fields.values())):
        raise GeofeedError('NIOS source.location_fields must map country, region and city to valid attribute names')
    resolved = {**DEFAULT_FIELDS, **fields}
    if len(set(resolved.values())) != 3:
        raise GeofeedError('NIOS geography attributes must have distinct names')
    return resolved


class InfobloxNIOS:
    def __init__(self, url, username, password, settings=None, http=None):
        self.settings = settings or {}
        self.fields = validate_settings(self.settings)
        self.requested = set(self.settings.get('network_refs', []))
        self.url = https_url(url)
        if not urlsplit(self.url).path.endswith('/wapi/v2.13.6'):
            raise GeofeedError('NIOS needs an HTTPS base ending /wapi/v2.13.6; other versions are not verified by this adapter')
        for value in (username, password):
            if not isinstance(value, str) or not value or len(value) > 16384 or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise GeofeedError('NIOS username or password is missing or invalid')
        if ':' in username:
            raise GeofeedError('NIOS Basic-auth username cannot contain a colon')
        self.headers = {'Authorization':'Basic ' + base64.b64encode((username + ':' + password).encode('utf-8')).decode('ascii')}
        self.http = http or JsonHTTP()

    def pages(self, kind):
        parameters = {'_paging':1, '_return_as_object':1, '_max_results':100,
                      '_return_fields':'network,network_view,extattrs'}
        refs, cursors = set(), set()
        for _ in range(MAX_PAGES):
            result = self.http.request(self.url + '/' + kind + '?' + urlencode(parameters),
                                       headers=self.headers, method='GET')
            if not isinstance(result, dict) or not isinstance(result.get('result'), list) or len(result['result']) > 100:
                raise GeofeedError('NIOS ' + kind + ' returned an invalid paged result')
            for row in result['result']:
                ref = native_ref(row.get('_ref') if isinstance(row, dict) else None, kind)
                if ref in refs:
                    raise GeofeedError('NIOS ' + kind + ' returned a duplicate network reference')
                if len(refs) >= MAX_RECORDS:
                    raise GeofeedError('NIOS exceeds the inventory record limit')
                refs.add(ref)
                yield row
            if 'next_page_id' not in result:
                return
            cursor = result['next_page_id']
            if (not isinstance(cursor, str) or not 1 <= len(cursor) <= 8192
                    or any(ord(c) < 33 or ord(c) > 126 for c in cursor)
                    or cursor in cursors or not result['result']):
                raise GeofeedError('NIOS ' + kind + ' has invalid, repeated or empty intermediate paging')
            cursors.add(cursor)
            # A page token is data, never a URL. Follow only the configured endpoint.
            parameters = {'_page_id':cursor}
        raise GeofeedError('NIOS ' + kind + ' exceeds the page limit')

    def snapshot(self):
        pools, sites, total, counts = [], [], 0, {}
        kinds = {ref.split('/', 1)[0] for ref in self.requested} or set(KINDS)
        for kind in KINDS:
            if kind not in kinds:
                continue
            counts[kind] = 0
            for row in self.pages(kind):
                total += 1
                counts[kind] += 1
                if total > MAX_RECORDS:
                    raise GeofeedError('NIOS exceeds the inventory record limit')
                ref = native_ref(row['_ref'], kind)
                identifier = normalized_id(ref)
                try:
                    value = row['network']
                    if not isinstance(value, str) or '/' not in value:
                        raise ValueError()
                    network = ipaddress.ip_network(value, strict=True)
                    if network.version != (4 if kind == 'network' else 6):
                        raise ValueError()
                except (KeyError, TypeError, ValueError):
                    raise GeofeedError(f'NIOS {identifier} has invalid or wrong-family network boundaries') from None
                view = row.get('network_view')
                if not isinstance(view, str) or not view or len(view) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in view):
                    raise GeofeedError(f'NIOS {identifier} has an invalid network view')
                values, error = {}, None
                attributes = row.get('extattrs', {})
                if not isinstance(attributes, dict):
                    error = 'invalid geography attribute container'
                else:
                    for field, name in self.fields.items():
                        entry = attributes.get(name)
                        if entry is None:
                            values[field] = None
                        elif (not isinstance(entry, dict) or not isinstance(entry.get('value'), str)
                              or len(entry['value']) > 512 or any(ord(c) < 32 or ord(c) == 127 for c in entry['value'])):
                            error = 'invalid declared geography attribute value'
                        else:
                            values[field] = entry['value']
                sid = 'location:' + identifier.split(':')[1]
                pools.append({'id':identifier, 'source_id':ref, 'source_kind':kind, 'network_view':view,
                    'name':'NIOS ' + identifier, 'ip_range':str(network), 'subnet':{'subnet':str(network)},
                    'site_id':sid, 'selected':ref in self.requested, 'location_error':error})
                sites.append({'id':sid, 'name':'Declared NIOS network location', 'addresses':[{'id':sid,
                    'country':values.get('country'), 'subdivision':values.get('region'), 'city':values.get('city')}]})
        if not total:
            raise GeofeedError('NIOS returned zero networks; not measured')
        return {'source':'infoblox_nios', 'support_level':'initial; fixture-tested, not live-tested',
            'api_contract':'NIOS WAPI 2.13.6 network/ipv6network and declared geography attributes',
            'site_resolution':'per-network declared attributes; synthetic location IDs, no native facility join claimed',
            'read_counts':counts, 'pools':pools, 'sites':sites}

    def for_publication(self, snapshot):
        if not self.requested:
            raise GeofeedError('Set NIOS source.network_refs to reviewed native references from discovery')
        selected = [p for p in snapshot['pools'] if p['selected']]
        if {p['source_id'] for p in selected} != self.requested:
            raise GeofeedError('Selected NIOS networks are missing or inaccessible; no partial inventory accepted')
        for row in selected:
            if row['location_error']:
                raise GeofeedError(f"NIOS {row['id']}: {row['location_error']}")
        return {**snapshot, 'pools':selected}
