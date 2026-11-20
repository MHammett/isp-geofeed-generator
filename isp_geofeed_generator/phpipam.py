"""Initial phpIPAM read-only subnet/location adapter."""
import ipaddress
import re
from .client import GeofeedError, JsonHTTP, https_url, record_id


class PhpIPAM:
    @staticmethod
    def location_settings(settings):
        mode = settings.get('location_mode', 'native')
        facilities = settings.get('facility_ids', [])
        if mode not in ('native', 'configured'):
            raise GeofeedError('phpIPAM location_mode must be native or configured')
        if (not isinstance(facilities, list) or any(not isinstance(sid, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', sid) for sid in facilities)
                or len(facilities) != len(set(facilities))):
            raise GeofeedError('phpIPAM facility_ids must contain unique valid facility ID strings')
        if mode == 'configured' and not facilities:
            raise GeofeedError('phpIPAM configured location mode needs explicit facility_ids')
        if mode == 'native' and facilities:
            raise GeofeedError('phpIPAM facility_ids needs location_mode: configured')
        return mode, facilities

    def __init__(self, url, app_id, token, settings=None, http=None):
        base = https_url(url)
        if not re.fullmatch(r'[A-Za-z0-9_-]+', app_id or ''):
            raise GeofeedError('PHPIPAM_APP_ID must be an application name, not a URL or secret')
        if not token or any(c.isspace() for c in token):
            raise GeofeedError('PHPIPAM_API_TOKEN is missing or invalid')
        self.base = base + '/api/' + app_id
        self.headers = {'phpipam-token': token}
        self.settings, self.http = settings or {}, http or JsonHTTP()
        self.location_mode, self.facilities = self.location_settings(self.settings)

    def collection(self, path):
        try:
            result = self.http.request(self.base + path, headers=self.headers, method='GET')
        except GeofeedError as exc:
            match = re.match(r'HTTP (401|403)\b', str(exc))
            if match:
                raise GeofeedError(f'phpIPAM authentication/read access refused (HTTP {match[1]}); a user token may have expired or the app mode/permissions may be wrong. For unattended runs use a read-only app in SSL with App code token mode') from None
            raise
        if not isinstance(result, dict) or result.get('success') is not True or result.get('code') != 200 or not isinstance(result.get('data'), list):
            raise GeofeedError('phpIPAM did not return a successful complete collection')
        rows, ids = result['data'], set()
        kind = {'/subnets/all/': 'subnet', '/tools/locations/': 'location'}.get(path, 'collection record')
        for row in rows:
            key = record_id(row)
            if key == '(unknown ID)':
                raise GeofeedError(f'phpIPAM {kind} (unknown ID) has a missing or invalid ID')
            if key in ids:
                raise GeofeedError(f'phpIPAM {kind} {key} is duplicated')
            ids.add(key)
        return rows

    def snapshot(self):
        subnets = self.collection('/subnets/all/')
        if not subnets:
            raise GeofeedError('phpIPAM returned zero subnets; not measured')
        locations = ([{'id': sid, 'name': 'Configured facility ' + sid} for sid in self.facilities]
                     if self.location_mode == 'configured' else self.collection('/tools/locations/'))
        sites = [{'id': str(s['id']), 'name': s.get('name') or str(s['id']),
            'addresses': [{'id': 'site:' + str(s['id']), 'country': None, 'subdivision': None, 'city': None}]}
            for s in locations]
        requested = {str(i) for i in self.settings.get('subnet_ids', [])}
        pools = []
        for row in subnets:
            try:
                value = str(row['subnet'])
                if value.isdecimal():
                    ipv6 = str(row.get('ip_version', row.get('version', ''))) == '6' or int(row['mask']) > 32
                    address = ipaddress.IPv6Address(int(value)) if ipv6 else ipaddress.ip_address(int(value))
                else:
                    address = ipaddress.ip_address(value)
                network = ipaddress.ip_network(f"{address}/{row['mask']}", strict=True)
            except (KeyError, TypeError, ValueError, AttributeError):
                raise GeofeedError(f'phpIPAM subnet {record_id(row)} has invalid or missing subnet/mask fields') from None
            native_location = row.get('location') if self.location_mode == 'native' else None
            if isinstance(native_location, dict):
                sid = native_location.get('id')
            elif native_location in (None, '', 0, '0', []):
                sid = None
            else:
                sid = native_location
            if sid is not None and not re.fullmatch(r'[0-9]{1,20}', str(sid)):
                raise GeofeedError(f'phpIPAM subnet {record_id(row)} location has an invalid ID; raw location details were not logged')
            sid = str(sid) if sid is not None else None
            pools.append({'id': 'subnet:' + str(row['id']), 'name': row.get('description') or str(network),
                'ip_range': str(network), 'subnet': {'subnet': str(network)}, 'site_id': sid,
                'scope_error': ('Configured location mode requires a reviewed pool_sites mapping to a declared facility'
                                if self.location_mode == 'configured' else 'Subnet location is unassigned; set the location or configure pool_sites'),
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
