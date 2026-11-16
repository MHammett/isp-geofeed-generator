"""Initial BillMax Core v1 selected IPv4 AP networks and native POP expansion."""
import ipaddress
import re
from urllib.parse import urlencode
from .client import GeofeedError, JsonHTTP, https_url, record_id


def validate_settings(settings):
    values = settings.get('ap_ids', [])
    if (not isinstance(values, list) or len(values) > 10000
            or any(not isinstance(v, str) or not re.fullmatch(r'[1-9][0-9]{0,19}', v) for v in values)
            or len(values) != len(set(values))):
        raise GeofeedError('BillMax source.ap_ids must contain unique positive digit-string IDs')
    if settings.get('auth_mode', 'api_key') not in ('api_key', 'userpass'):
        raise GeofeedError('BillMax source.auth_mode must be api_key or userpass')


def api_token(value, label):
    if not isinstance(value, str) or not value or len(value) > 16384 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
        raise GeofeedError('BillMax ' + label + ' is missing or invalid')
    return value


class BillMax:
    def __init__(self, url, key, settings=None, *, username=None, password=None, http=None):
        self.settings = settings or {}
        validate_settings(self.settings)
        self.url = https_url(url)
        self.key = api_token(key, 'API key')
        self.username, self.password = username, password
        self.http = http or JsonHTTP()
        self.requested = self.settings.get('ap_ids', [])
        if self.settings.get('auth_mode') == 'userpass':
            for value, label in ((username, 'username'), (password, 'password')):
                if not isinstance(value, str) or not value or len(value) > 16384 or any(ord(c) < 32 or ord(c) == 127 for c in value):
                    raise GeofeedError('BillMax ' + label + ' is missing or invalid')

    def headers(self):
        headers = {'api_key': self.key}
        if self.settings.get('auth_mode') == 'userpass':
            result = self.http.request(self.url + '/login', headers=dict(headers),
                body={'username': self.username, 'password': self.password}, method='POST')
            if not isinstance(result, dict):
                raise GeofeedError('BillMax login returned an invalid session response')
            headers['Authorization'] = 'Bearer ' + api_token(result.get('BXSESSIONID'), 'session token')
        return headers

    def read(self, path, headers, parameters):
        return self.http.request(self.url + path + '?' + urlencode(parameters), headers=headers, method='GET')

    def discover_aps(self, headers):
        # Publication uses explicit detail reads, not this offset-based directory.
        rows, seen, offset, last = [], set(), 0, -1
        for _ in range(1000):
            batch = self.read('/aps', headers, {'flds': 'id,name,networkMask,pop,status',
                'limitStart': offset, 'limitNrows': 100, 'orderBy': 'id ASC'})
            if not isinstance(batch, list) or len(batch) > 100:
                raise GeofeedError('BillMax AP directory returned an invalid page')
            if not batch:
                if not rows:
                    raise GeofeedError('BillMax returned zero APs; not measured')
                return rows
            for row in batch:
                rid = record_id(row)
                if rid == '(unknown ID)' or int(rid) < 1 or int(rid) <= last or rid in seen:
                    raise GeofeedError('BillMax AP directory has invalid, repeated or unordered IDs')
                seen.add(rid); last = int(rid)
                # Do not retain unrequested fields, including notes or customer data.
                rows.append({k: row.get(k) for k in ('id', 'name', 'networkMask', 'pop', 'status')})
            offset += len(batch)  # A server may clamp the requested page size.
        raise GeofeedError('BillMax AP directory exceeds the page limit')

    def snapshot(self):
        headers = self.headers()
        pools, sites = [], {}
        directory = self.discover_aps(headers) if not self.requested else []
        for rid in self.requested:
            result = self.read('/aps/' + rid, headers,
                {'pop': 'true', 'notes': 'false', 'tickets': 'false', 'active': 'true'})
            if not isinstance(result, list) or len(result) != 1 or record_id(result[0]) != rid:
                raise GeofeedError(f'BillMax AP {rid} is missing, inaccessible or returned an invalid detail response')
            row = result[0]
            try:
                value = row['networkMask']
                if not isinstance(value, str) or '/' not in value:
                    raise ValueError()
                network = ipaddress.ip_network(value, strict=True)
                # The reviewed schema only documents IPv4 /16 and /24 AP masks.
                if network.version != 4 or network.prefixlen not in (16, 24) or str(network) != value:
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                raise GeofeedError(f'BillMax AP {rid} needs a canonical IPv4 /16 or /24 networkMask; other boundaries are not verified by this adapter') from None
            linked = row.get('_pop')
            if not isinstance(linked, list) or len(linked) != 1 or record_id(linked[0]) == '(unknown ID)' or int(record_id(linked[0])) < 1:
                raise GeofeedError(f'BillMax AP {rid} needs exactly one expanded native POP with a stable ID')
            pop = linked[0]
            pid = 'pop:' + record_id(pop)
            # Discard street address, postal code, coordinates and operational notes.
            site = {'id': pid, 'name': 'BillMax ' + pid, 'addresses': [{'id': pid,
                'country': pop.get('country'), 'subdivision': pop.get('stateProvince'), 'city': pop.get('city')}]}
            if pid in sites and sites[pid] != site:
                raise GeofeedError(f'BillMax {pid} location changed or conflicts across selected APs')
            sites[pid] = site
            pools.append({'id': 'ap:' + rid, 'name': 'BillMax AP ' + rid,
                'ip_range': str(network), 'subnet': {'subnet': str(network)}, 'site_id': pid,
                'source_kind': 'ap_network', 'source_id': rid})
        return {'source': 'billmax', 'support_level': 'initial; schema/fixture-tested, not live-tested',
            'api_contract': 'BillMax Core v1.0.0 selected AP networkMask with expanded _pop',
            'pools': pools, 'sites': list(sites.values()), 'ap_directory': directory}

    def for_publication(self, snapshot):
        if not self.requested or len(snapshot['pools']) != len(self.requested):
            raise GeofeedError('Set source.ap_ids to reviewed BillMax AP IDs whose whole IPv4 network belongs at the linked POP')
        return snapshot
