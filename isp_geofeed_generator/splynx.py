"""Initial Splynx API v2 adapter, based on the vendor's release-6.0 schema."""
import hashlib
import hmac
import ipaddress
import time
from urllib.parse import urlencode
from .client import GeofeedError, JsonHTTP, https_url, record_id


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
        kind = {'/admin/networking/network-sites': 'network site', '/admin/networking/ipv4': 'IPv4 network',
                '/admin/networking/ipv6': 'IPv6 network'}.get(path, 'collection record')
        for _ in range(10000):
            params = urlencode({'limit': 100, 'offset': offset, 'order[id]': 'ASC'})
            rows = self.http.request(self.base + path + '?' + params, headers=self.headers(), method='GET')
            if not isinstance(rows, list):
                raise GeofeedError(f'Splynx {kind} collection at offset {offset} is not an array; no partial result accepted')
            if not rows:
                return result
            for row in rows:
                key = record_id(row)
                if key == '(unknown ID)':
                    raise GeofeedError(f'Splynx {kind} (unknown ID) has a missing or invalid ID at offset {offset}')
                if key in seen:
                    raise GeofeedError(f'Splynx {kind} {key} is duplicated; pagination may have been ignored')
                seen.add(key); result.append(row)
            # Continue even after a short page: server-side limits may be lower.
            offset += len(rows)
        raise GeofeedError('Splynx pagination limit exceeded')

    @staticmethod
    def network_fields(row, version):
        label = f'Splynx IPv{version} network {record_id(row)}'
        try:
            prefix = row['mask'] if version == 4 else row['prefix']
            network = ipaddress.ip_network(f"{row['network']}/{prefix}", strict=True)
            if network.version != version:
                raise ValueError()
            ip_range = str(network)
            if version == 6 and any(row.get(key) not in (None, '') for key in ('range_from', 'range_to')):
                if not isinstance(row.get('range_from'), str) or not isinstance(row.get('range_to'), str):
                    raise ValueError()
                first, last = ipaddress.IPv6Address(row['range_from']), ipaddress.IPv6Address(row['range_to'])
                if first > last or first not in network or last not in network:
                    raise ValueError()
                ip_range = str(first) + '-' + str(last)
            return network, ip_range
        except (KeyError, TypeError, ValueError, AttributeError):
            raise GeofeedError(f'{label} has invalid or missing network/mask/prefix or range fields') from None

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
                network, ip_range = self.network_fields(row, version)
                pid = f"ipv{version}:{row['id']}"
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
