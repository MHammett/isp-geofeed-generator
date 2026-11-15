"""Initial Splynx API v2 adapter, based on the vendor's release-6.0 schema."""
import hashlib
import hmac
import ipaddress
import time
from urllib.parse import urlencode
from .client import GeofeedError, JsonHTTP, https_url


class Splynx:
    def __init__(self, url, key, secret, settings=None, http=None):
        base = https_url(url)
        self.base = base if base.endswith('/api/2.0') else base + '/api/2.0'
        if not key or not secret or any(c in key + secret for c in '\r\n\x00'):
            raise GeofeedError('Splynx API key/secret is missing or invalid')
        self.key, self.secret = key, secret
        self.settings, self.http = settings or {}, http or JsonHTTP()
        self.nonce = 0

    def headers(self):
        self.nonce = max(self.nonce + 1, time.time_ns() // 10_000_000)
        nonce = str(self.nonce)
        signature = hmac.new(self.secret.encode(), (nonce + self.key).encode(), hashlib.sha256).hexdigest().upper()
        return {'Authorization': 'Splynx-EA (' + urlencode({'key': self.key, 'nonce': nonce, 'signature': signature}) + ')'}

    def pages(self, path):
        result, seen, offset = [], set(), 0
        for _ in range(10000):
            params = urlencode({'limit': 100, 'offset': offset, 'order[id]': 'ASC'})
            rows = self.http.request(self.base + path + '?' + params, headers=self.headers(), method='GET')
            if not isinstance(rows, list):
                raise GeofeedError('Splynx collection is not an array; no partial result accepted')
            if not rows:
                return result
            for row in rows:
                if not isinstance(row, dict) or row.get('id') is None:
                    raise GeofeedError('Invalid Splynx collection record')
                key = str(row['id'])
                if key in seen:
                    raise GeofeedError('Duplicate Splynx record; pagination may have been ignored')
                seen.add(key); result.append(row)
            # Continue even after a short page: server-side limits may be lower.
            offset += len(rows)
        raise GeofeedError('Splynx pagination limit exceeded')

    def snapshot(self):
        sites = self.pages('/admin/networking/network-sites')
        normalized_sites = [{'id': str(s['id']), 'name': s.get('title') or str(s['id']),
            'addresses': [{'id': 'site:' + str(s['id']), 'country': None, 'subdivision': None, 'city': None}]}
            for s in sites]
        pools = []
        selections = {str(i) for i in self.settings.get('network_ids', [])}
        location_sites = {str(k): str(v) for k, v in self.settings.get('location_sites', {}).items()}
        for version in (4, 6):
            for row in self.pages(f'/admin/networking/ipv{version}'):
                prefix = row['mask'] if version == 4 else row['prefix']
                network = ipaddress.ip_network(f"{row['network']}/{prefix}", strict=True)
                if network.version != version:
                    raise GeofeedError('Splynx network address family does not match endpoint')
                pid = f"ipv{version}:{row['id']}"
                ip_range = str(network)
                if version == 6 and (row.get('range_from') or row.get('range_to')):
                    if not row.get('range_from') or not row.get('range_to'):
                        raise GeofeedError('Splynx IPv6 range has only one boundary')
                    ip_range = row['range_from'] + '-' + row['range_to']
                pools.append({'id': pid, 'name': row.get('title') or pid, 'ip_range': ip_range,
                    'subnet': {'subnet': str(network)}, 'site_id': location_sites.get(str(row.get('location_id'))),
                    'administrative_location_id': str(row.get('location_id')),
                    'scope_error': 'Configure pool_sites or a reviewed administrative-location to network-site mapping',
                    'selected': pid in selections and row.get('network_type') == 'endnet' and row.get('type_of_usage') in ('pool', 'static')})
        if not pools:
            raise GeofeedError('Splynx returned zero IP networks; not measured')
        return {'source': 'splynx', 'support_level': 'initial; fixture-tested, not live-tested', 'pools': pools, 'sites': normalized_sites}

    def for_publication(self, snapshot):
        requested = {str(i) for i in self.settings.get('network_ids', [])}
        if not requested:
            raise GeofeedError('Set source.network_ids to the reviewed ipv4:<id>/ipv6:<id> records')
        found = {p['id'] for p in snapshot['pools']}
        if requested - found:
            raise GeofeedError('Configured Splynx networks no longer exist')
        selected = [p for p in snapshot['pools'] if p['selected']]
        if len(selected) != len(requested):
            raise GeofeedError('Selected Splynx records must be endnet networks with pool/static usage')
        return {**snapshot, 'pools': selected}
