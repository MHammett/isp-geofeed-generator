"""Initial phpIPAM read-only subnet/location adapter."""
import ipaddress
import re
from .client import GeofeedError, JsonHTTP, https_url


class PhpIPAM:
    def __init__(self, url, app_id, token, settings=None, http=None):
        base = https_url(url)
        if not re.fullmatch(r'[A-Za-z0-9_-]+', app_id or ''):
            raise GeofeedError('PHPIPAM_APP_ID must be an application name, not a URL or secret')
        if not token or any(c.isspace() for c in token):
            raise GeofeedError('PHPIPAM_API_TOKEN is missing or invalid')
        self.base = base + '/api/' + app_id
        self.headers = {'phpipam-token': token}
        self.settings, self.http = settings or {}, http or JsonHTTP()

    def collection(self, path):
        result = self.http.request(self.base + path, headers=self.headers, method='GET')
        if not isinstance(result, dict) or result.get('success') is not True or result.get('code') != 200 or not isinstance(result.get('data'), list):
            raise GeofeedError('phpIPAM did not return a successful complete collection')
        rows, ids = result['data'], set()
        for row in rows:
            if not isinstance(row, dict) or row.get('id') is None or str(row['id']) in ids:
                raise GeofeedError('Invalid or duplicate phpIPAM collection record')
            ids.add(str(row['id']))
        return rows

    def snapshot(self):
        subnets = self.collection('/subnets/all/')
        locations = self.collection('/tools/locations/')
        if not subnets:
            raise GeofeedError('phpIPAM returned zero subnets; not measured')
        sites = [{'id': str(s['id']), 'name': s.get('name') or str(s['id']),
            'addresses': [{'id': 'site:' + str(s['id']), 'country': None, 'subdivision': None, 'city': None}]}
            for s in locations]
        requested = {str(i) for i in self.settings.get('subnet_ids', [])}
        pools = []
        for row in subnets:
            value = str(row['subnet'])
            if value.isdecimal():
                ipv6 = str(row.get('ip_version', row.get('version', ''))) == '6' or int(row['mask']) > 32
                address = ipaddress.IPv6Address(int(value)) if ipv6 else ipaddress.ip_address(int(value))
            else:
                address = ipaddress.ip_address(value)
            network = ipaddress.ip_network(f"{address}/{row['mask']}", strict=True)
            sid = row.get('location')
            sid = str(sid) if sid not in (None, '', 0, '0') else None
            pools.append({'id': 'subnet:' + str(row['id']), 'name': row.get('description') or str(network),
                'ip_range': str(network), 'subnet': {'subnet': str(network)}, 'site_id': sid,
                'scope_error': 'Subnet location is unassigned; set the location or configure pool_sites',
                'selected': str(row['id']) in requested and str(row.get('isFolder', '0')) not in ('1', 'True')})
        return {'source': 'phpipam', 'support_level': 'initial; fixture-tested, not live-tested', 'pools': pools, 'sites': sites}

    def for_publication(self, snapshot):
        requested = {'subnet:' + str(i) for i in self.settings.get('subnet_ids', [])}
        if not requested:
            raise GeofeedError('Set source.subnet_ids to reviewed phpIPAM subnets')
        found = {p['id'] for p in snapshot['pools']}
        if requested - found:
            raise GeofeedError('Configured phpIPAM subnets no longer exist')
        selected = [p for p in snapshot['pools'] if p['selected']]
        if len(selected) != len(requested):
            raise GeofeedError('Selected phpIPAM records must be subnets, not folders')
        return {**snapshot, 'pools': selected}
