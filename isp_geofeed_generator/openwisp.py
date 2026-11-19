"""Initial OpenWISP IPAM 1.3.1 selected-subnet reader; no inferred geography."""
import ipaddress
from uuid import UUID

from .client import GeofeedError, JsonHTTP, https_url

MAX_SUBNETS = 256


def uuid_value(value):
    if isinstance(value, str) and len(value) == 36:
        try:
            parsed = UUID(value)
            if parsed.int and str(parsed) == value:
                return value
        except ValueError:
            pass
    raise GeofeedError('OpenWISP needs canonical, nonzero lowercase UUIDs')


def validate_settings(settings):
    uuid_value(settings.get('organization_id'))
    selected = settings.get('subnet_ids')
    if not isinstance(selected, list) or not 1 <= len(selected) <= MAX_SUBNETS:
        raise GeofeedError('OpenWISP source.subnet_ids must select 1 to 256 subnet UUIDs')
    for value in selected:
        uuid_value(value)
    if len(selected) != len(set(selected)):
        raise GeofeedError('OpenWISP source.subnet_ids contains duplicate UUIDs')


class OpenWISP:
    def __init__(self, url, token, settings=None, http=None):
        self.settings = settings or {}
        validate_settings(self.settings)
        self.requested = tuple(self.settings['subnet_ids'])
        self.organization = self.settings['organization_id']
        # Base is the installation root (or its reverse-proxy mount path).
        self.url = https_url(url)
        if (not isinstance(token, str) or not 1 <= len(token) <= 16384
                or any(ord(c) < 33 or ord(c) > 126 for c in token)):
            raise GeofeedError('OpenWISP API token is missing or invalid')
        self.headers = {'Authorization': 'Bearer ' + token}
        self.http = http or JsonHTTP()

    def snapshot(self):
        pools, sites = [], []
        for rid in self.requested:
            row = self.http.request(self.url + '/api/v1/ipam/subnet/' + rid + '/',
                                    headers=self.headers, method='GET')
            if not isinstance(row, dict) or row.get('id') != rid:
                raise GeofeedError(f'OpenWISP subnet {rid} returned a missing or mismatched detail record; no partial inventory accepted')
            # Shared (null organization) subnets need a separate explicit policy.
            if row.get('organization') != self.organization:
                raise GeofeedError(f'OpenWISP subnet {rid} does not match the configured organization; no partial inventory accepted')
            try:
                value = row['subnet']
                if not isinstance(value, str) or not 3 <= len(value) <= 64 or '/' not in value:
                    raise ValueError()
                network = ipaddress.ip_network(value, strict=True)
                if str(network) != value:
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                raise GeofeedError(f'OpenWISP subnet {rid} has invalid or noncanonical network boundaries') from None
            identifier = 'subnet:' + rid
            pools.append({'id': identifier, 'source_id': rid, 'source_kind': 'subnet',
                'name': 'OpenWISP ' + identifier, 'ip_range': str(network),
                'subnet': {'subnet': str(network)}, 'site_id': identifier})
            # This is a configuration slot, not a claimed native facility.
            sites.append({'id': identifier, 'name': 'Configured OpenWISP subnet location',
                          'addresses': [{'id': identifier}]})
        return {'source': 'openwisp', 'support_level': 'initial; fixture-tested, not live-tested',
            'api_contract': 'OpenWISP IPAM 1.3.1 selected subnet details',
            'site_resolution': 'configured per-subnet location; no native facility join claimed',
            'selection_scope': 'explicit subnet IDs in one organization; not complete instance inventory',
            'pools': pools, 'sites': sites}

    def for_publication(self, snapshot):
        if ([p.get('source_id') for p in snapshot.get('pools', [])] != list(self.requested)):
            raise GeofeedError('Selected OpenWISP subnets are missing or changed; no partial inventory accepted')
        return snapshot
