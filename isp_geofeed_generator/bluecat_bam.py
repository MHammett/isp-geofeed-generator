"""Initial BAM RESTful v2 9.6 selected network profile; no session mutations."""
import base64
import ipaddress
import re
from urllib.parse import urlsplit

from .client import GeofeedError, JsonHTTP, https_url

MAX_NETWORKS = 256
TYPES = {'IPv4Network': 4, 'IPv6Network': 6}


def selected_id(value):
    if type(value) is int and 0 < value < 10**20:
        return str(value)
    if isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,19}', value):
        return value
    raise GeofeedError('BlueCat BAM needs positive bounded numeric IDs')


def validate_settings(settings):
    selected_id(settings.get('configuration_id'))
    values = settings.get('network_ids')
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_NETWORKS:
        raise GeofeedError('BlueCat BAM source.network_ids must select 1 to 256 IDs')
    ids = [selected_id(value) for value in values]
    if len(set(ids)) != len(ids):
        raise GeofeedError('BlueCat BAM network selection contains duplicate IDs')


class BlueCatBAM:
    def __init__(self, url, username, token, settings=None, http=None):
        settings = settings or {}
        validate_settings(settings)
        self.requested = tuple(selected_id(value) for value in settings['network_ids'])
        self.configuration = selected_id(settings['configuration_id'])
        self.url = https_url(url)
        if not urlsplit(self.url).path.endswith('/api/v2'):
            raise GeofeedError('BlueCat BAM needs an HTTPS base ending /api/v2; Legacy v1 and Micetro are different APIs')
        for value in (username, token):
            if (not isinstance(value, str) or not 1 <= len(value) <= 16384
                    or any(ord(c) < 33 or ord(c) > 126 for c in value)):
                raise GeofeedError('BlueCat BAM username or API token is missing or invalid')
        if ':' in username:
            raise GeofeedError('BlueCat BAM Basic-auth username cannot contain a colon')
        encoded = base64.b64encode((username + ':' + token).encode('ascii')).decode('ascii')
        self.headers = {'Authorization': 'Basic ' + encoded, 'Accept': 'application/hal+json'}
        self.http = http or JsonHTTP()

    def snapshot(self):
        pools, sites = [], []
        for rid in self.requested:
            row = self.http.request(self.url + '/networks/' + rid, headers=self.headers, method='GET')
            if not isinstance(row, dict) or type(row.get('id')) is not int or str(row['id']) != rid:
                raise GeofeedError(f'BlueCat BAM network {rid} returned a missing or mismatched numeric ID; no partial inventory accepted')
            configuration = row.get('configuration')
            if (not isinstance(configuration, dict) or type(configuration.get('id')) is not int
                    or str(configuration['id']) != self.configuration):
                raise GeofeedError(f'BlueCat BAM network {rid} does not match the configured configuration; no partial inventory accepted')
            kind = row.get('type')
            if not isinstance(kind, str) or kind not in TYPES:
                raise GeofeedError(f'BlueCat BAM network {rid} has an unsupported resource type')
            try:
                value = row['range']
                if (not isinstance(value, str) or len(value) > 128
                        or re.fullmatch(r'[^%\s/]+/(?:0|[1-9][0-9]{0,2})', value) is None):
                    raise ValueError()
                network = ipaddress.ip_network(value, strict=True)
                if network.version != TYPES[kind]:
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                raise GeofeedError(f'BlueCat BAM network {rid} needs exact CIDR boundaries matching its resource family') from None
            identifier = 'network:' + rid
            pools.append({'id': identifier, 'source_id': rid, 'source_kind': kind,
                'name': 'BlueCat BAM ' + identifier, 'ip_range': str(network),
                'subnet': {'subnet': str(network)}, 'site_id': identifier, 'site_id_source': 'configuration'})
            sites.append({'id': identifier, 'name': 'Configured BlueCat network location',
                          'addresses': [{'id': identifier}]})
        return {'source': 'bluecat_bam', 'support_level': 'initial; public-example/fixture-tested, not live-tested',
            'api_contract': 'BAM RESTful v2 9.6 selected network resources; username plus existing apiToken',
            'site_resolution': 'configured per-network location; native effective-location join not verified',
            'selection_scope': 'explicit network IDs in one configuration; not complete inventory',
            'pools': pools, 'sites': sites}

    def for_publication(self, snapshot):
        if [row.get('source_id') for row in snapshot.get('pools', [])] != list(self.requested):
            raise GeofeedError('Selected BlueCat BAM networks are missing or changed; no partial inventory accepted')
        return snapshot
