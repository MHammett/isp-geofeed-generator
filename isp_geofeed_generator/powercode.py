"""Initial Powercode legacy readAddressRanges adapter (public V20 docs)."""
import ipaddress
import re
from .client import GeofeedError, JsonHTTP, https_url


def selected_ids(settings, key, *, numeric=False):
    values = settings.get(key, [])
    pattern = r"[0-9]{1,20}" if numeric else r"[A-Za-z0-9_.:-]{1,128}"
    if not isinstance(values, list) or any(isinstance(v, bool) or not re.fullmatch(pattern, str(v)) for v in values):
        raise GeofeedError(f"Powercode source.{key} must be a list of valid IDs")
    result = [str(v) for v in values]
    if len(result) != len(set(result)):
        raise GeofeedError(f"Powercode source.{key} contains duplicate IDs")
    return set(result)


def exact_range(value, record_id):
    try:
        if not isinstance(value, str) or value.count('-') != 1:
            raise ValueError()
        start, end = (ipaddress.ip_address(s.strip()) for s in value.split('-'))
        if start.version != end.version or int(start) > int(end):
            raise ValueError()
        length = start.max_prefixlen - (int(start) ^ int(end)).bit_length()
        cls = ipaddress.IPv4Network if start.version == 4 else ipaddress.IPv6Network
        # This envelope only satisfies the core's containment check. It is not
        # an allocation returned by Powercode, and is never published as a pool.
        envelope = cls((int(start), length), strict=False)
        return f"{start}-{end}", str(envelope)
    except (ValueError, TypeError):
        raise GeofeedError(f"Powercode range {record_id} has invalid, reversed or mixed-family boundaries") from None


class Powercode:
    def __init__(self, url, key, settings=None, http=None):
        base = https_url(url)
        self.url = base if base.endswith('/api/1/index.php') else base + '/api/1/index.php'
        if not key or any(c.isspace() for c in key):
            raise GeofeedError('POWERCODE_API_KEY is missing or invalid')
        self.key, self.settings, self.http = key, settings or {}, http or JsonHTTP()
        self.requested = selected_ids(self.settings, 'range_ids', numeric=True)
        self.facilities = selected_ids(self.settings, 'facility_ids')

    def snapshot(self):
        result = self.http.request(self.url, form={'apiKey': self.key, 'action': 'readAddressRanges'}, method='POST')
        if (not isinstance(result, dict) or isinstance(result.get('statusCode'), bool)
                or result.get('statusCode') not in (0, '0') or not isinstance(result.get('ranges'), list)):
            raise GeofeedError('Powercode did not return a successful address range collection; no partial result accepted')
        if not result['ranges']:
            raise GeofeedError('Powercode returned zero ranges; not measured')
        pools, seen = [], set()
        for row in result['ranges']:
            rid = str(row.get('addressRangeID', '')) if isinstance(row, dict) else ''
            if not re.fullmatch(r'[0-9]{1,20}', rid) or rid in seen:
                raise GeofeedError('Powercode returned an invalid or duplicate addressRangeID')
            seen.add(rid)
            value, envelope = exact_range(row.get('range'), rid)
            pools.append({'id': 'range:' + rid, 'name': 'Powercode range ' + rid,
                'ip_range': value, 'subnet': {'subnet': envelope}, 'parent_source': 'derived_envelope',
                'site_id': None, 'selected': rid in self.requested,
                'scope_error': 'Legacy range export has no facility ID; configure pool_sites and source.facility_ids'})
        sites = [{'id': sid, 'name': 'Configured facility ' + sid,
                  'addresses': [{'id': 'site:' + sid, 'country': None, 'subdivision': None, 'city': None}]}
                 for sid in sorted(self.facilities)]
        return {'source': 'powercode', 'support_level': 'initial; fixture-tested, not live-tested',
                'api_contract': 'legacy readAddressRanges, public V20 reference',
                'site_resolution': 'explicit operator mappings; no native join claimed', 'pools': pools, 'sites': sites}

    def for_publication(self, snapshot):
        if not self.requested:
            raise GeofeedError('Set source.range_ids to reviewed Powercode addressRangeID values')
        selected = [p for p in snapshot['pools'] if p['selected']]
        if len(selected) != len(self.requested):
            raise GeofeedError('Configured Powercode ranges no longer exist')
        return {**snapshot, 'pools': selected}
