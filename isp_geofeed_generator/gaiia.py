"""Initial gaiia public GraphQL network-site/IP-block reader."""
import base64
import ipaddress
import re
from .client import GeofeedError, JsonHTTP, https_url

SITES_QUERY = '''query GeofeedSites($first: Int!, $after: String) {
  networkSites(first: $first, after: $after) {
    totalCount pageInfo { hasNextPage endCursor }
    nodes { id name archivedAt address { id country region locality } }
  }
}'''
BLOCKS_QUERY = '''query GeofeedSiteBlocks($id: GlobalID!, $first: Int!, $after: String) {
  networkSite(id: $id) {
    id archivedAt ipBlocks(first: $first, after: $after) {
      totalCount pageInfo { hasNextPage endCursor }
      nodes { id networkSiteId block }
    }
  }
}'''


def native_id(value):
    if not isinstance(value, str) or not value or len(value) > 512 or any(c.isspace() or ord(c) < 32 for c in value):
        raise GeofeedError('gaiia returned a missing or invalid opaque ID')
    return value


def normalized_id(kind, value):
    # GlobalID is opaque and may contain characters outside the core ID format.
    encoded = base64.urlsafe_b64encode(native_id(value).encode()).decode().rstrip('=')
    result = kind + ':' + encoded
    if len(result) > 128:
        raise GeofeedError('gaiia opaque ID exceeds the normalized ID length limit; report a sanitized schema example')
    return result


def selected_ids(settings, key):
    values = settings.get(key, [])
    if not isinstance(values, list):
        raise GeofeedError(f'gaiia source.{key} must be a list of native GlobalID strings')
    result = [native_id(value) for value in values]
    if len(result) != len(set(result)):
        raise GeofeedError(f'gaiia source.{key} contains duplicate IDs')
    return set(result)


class Gaiia:
    def __init__(self, url, key, settings=None, http=None):
        self.url = https_url(url)
        if not key or any(c.isspace() for c in key):
            raise GeofeedError('GAIIA_API_KEY is missing or invalid')
        self.headers = {'X-Gaiia-Api-Key': key}
        self.settings, self.http = settings or {}, http or JsonHTTP()
        self.site_ids = selected_ids(self.settings, 'site_ids')
        self.block_ids = selected_ids(self.settings, 'block_ids')
        if self.site_ids and self.block_ids:
            raise GeofeedError('Choose gaiia source.site_ids or source.block_ids, not both')

    def query(self, document, variables):
        result = self.http.request(self.url, body={'query': document, 'variables': variables}, headers=self.headers, method='POST')
        if not isinstance(result, dict) or result.get('errors') or not isinstance(result.get('data'), dict):
            raise GeofeedError('gaiia returned GraphQL errors or no data; no partial result accepted')
        return result['data']

    def pages(self, fetch, label):
        rows, seen_ids, cursors, cursor, total = [], set(), set(), None, None
        for _ in range(10000):
            result = fetch(cursor)
            try:
                count, batch, info = result['totalCount'], result['nodes'], result['pageInfo']
                following, next_cursor = info['hasNextPage'], info['endCursor']
                if (isinstance(count, bool) or not isinstance(count, int) or count < 0
                        or not isinstance(batch, list) or not isinstance(following, bool)):
                    raise ValueError()
                if total is None:
                    total = count
                if total != count:
                    raise GeofeedError(f'gaiia {label} count changed during pagination')
                for row in batch:
                    if not isinstance(row, dict):
                        raise ValueError()
                    rid = native_id(row.get('id'))
                    if rid in seen_ids:
                        raise GeofeedError(f'gaiia {label} returned a duplicate record')
                    seen_ids.add(rid); rows.append(row)
                if not following:
                    if len(rows) != total:
                        raise GeofeedError(f'gaiia {label} result count is incomplete')
                    return rows
                if (not batch or len(rows) >= total or not isinstance(next_cursor, str)
                        or not next_cursor or len(next_cursor) > 4096 or next_cursor in cursors):
                    raise GeofeedError(f'gaiia {label} returned an invalid or repeated continuation cursor')
                cursors.add(next_cursor); cursor = next_cursor
            except (KeyError, TypeError, ValueError):
                raise GeofeedError(f'gaiia {label} connection metadata is invalid') from None
        raise GeofeedError(f'gaiia {label} pagination limit exceeded')

    def snapshot(self):
        def site_page(cursor):
            return self.query(SITES_QUERY, {'first': 100, 'after': cursor}).get('networkSites')
        sites = self.pages(site_page, 'sites')
        if not sites:
            raise GeofeedError('gaiia returned zero network sites; not measured')
        normalized_sites, pools, seen_blocks = [], [], set()
        for site in sites:
            sid = normalized_id('site', site['id'])
            if 'archivedAt' not in site or (site['archivedAt'] is not None and not isinstance(site['archivedAt'], str)):
                raise GeofeedError(f'gaiia {sid} has invalid archive status')
            if not isinstance(site.get('name'), str) or not isinstance(site.get('address'), dict):
                raise GeofeedError(f'gaiia {sid} has invalid name or address data')
            address = site['address']
            if any(not isinstance(address.get(k), str) for k in ('country', 'region', 'locality')):
                raise GeofeedError(f'gaiia {sid} is missing structured country, region or locality fields')
            country, region = address['country'].strip().upper(), address['region'].strip().upper()
            if re.fullmatch(r'[A-Z]{2}', country) and re.fullmatch(r'[A-Z0-9]{1,3}', region):
                region = country + '-' + region
            normalized_sites.append({'id': sid, 'source_id': site['id'], 'name': site['name'],
                'archived': site['archivedAt'] is not None,
                'addresses': [{'id': 'site-address', 'country': country, 'subdivision': region, 'city': address['locality']}]})
            def block_page(cursor):
                owner = self.query(BLOCKS_QUERY, {'id': site['id'], 'first': 100, 'after': cursor}).get('networkSite')
                if (not isinstance(owner, dict) or owner.get('id') != site['id']
                        or 'archivedAt' not in owner or owner['archivedAt'] != site['archivedAt']):
                    raise GeofeedError(f'gaiia {sid} disappeared or changed archive status while reading blocks')
                return owner.get('ipBlocks')
            for row in self.pages(block_page, 'blocks for ' + sid):
                pid = normalized_id('block', row['id'])
                if row.get('networkSiteId') != site['id'] or row['id'] in seen_blocks:
                    raise GeofeedError(f'gaiia {pid} has a conflicting or duplicate site assignment')
                seen_blocks.add(row['id'])
                try:
                    network = ipaddress.ip_network(row['block'], strict=True)
                except (KeyError, TypeError, ValueError):
                    raise GeofeedError(f'gaiia {pid} has a missing or noncanonical IP block') from None
                chosen = site['id'] in self.site_ids or row['id'] in self.block_ids
                pools.append({'id': pid, 'source_id': row['id'], 'source_site_id': site['id'],
                    'name': pid, 'ip_range': str(network), 'subnet': {'subnet': str(network)},
                    'site_id': sid, 'selected': chosen and site['archivedAt'] is None})
        if not pools:
            raise GeofeedError('gaiia returned zero site IP blocks; not measured')
        return {'source': 'gaiia', 'support_level': 'initial; public schema and fixtures, not live-tested',
                'pools': pools, 'sites': normalized_sites}

    def for_publication(self, snapshot):
        if not self.site_ids and not self.block_ids:
            raise GeofeedError('Set source.site_ids or source.block_ids to reviewed native gaiia GlobalID strings')
        active_sites = {s['source_id'] for s in snapshot['sites'] if not s['archived']}
        found = {p['source_id'] for p in snapshot['pools'] if p['selected']}
        if self.site_ids - active_sites or self.block_ids - found:
            raise GeofeedError('Configured gaiia sites/blocks are missing or archived')
        chosen = [p for p in snapshot['pools'] if p['selected']]
        # A selected site losing every block is not an empty success.
        represented = {p['source_site_id'] for p in chosen}
        if not chosen or self.site_ids - represented:
            raise GeofeedError('A selected gaiia site has no IP blocks; review before withdrawing its coverage')
        return {**snapshot, 'pools': chosen}
