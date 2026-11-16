"""Explicit alternate NetBox models; no parent-prefix or name-based guesses."""
import re
from .client import GeofeedError, record_id
from .locations import COARSE_FIELDS, validate_location


def location_settings(settings):
    mode = settings.get('location_mode', 'site')
    if mode not in ('site', 'prefix_fields', 'region_hierarchy'):
        raise GeofeedError('NetBox location_mode must be site, prefix_fields or region_hierarchy')
    configured = settings.get('location_fields', {})
    if (not isinstance(configured, dict) or set(configured) - COARSE_FIELDS or
            any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', v) for v in configured.values())):
        raise GeofeedError('NetBox location_fields must map country/region/city to custom field names')
    if mode == 'region_hierarchy' and configured:
        raise GeofeedError('NetBox region_hierarchy uses explicit ISO country/state/city node names, not location_fields')
    enabled = settings.get('location_enabled_field')
    if 'location_enabled_field' in settings and (mode != 'prefix_fields' or not isinstance(enabled, str)
                                               or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', enabled)):
        raise GeofeedError('NetBox location_enabled_field needs prefix_fields mode and a custom field name')
    return mode, {'country':'geofeed_country','region':'geofeed_region','city':'geofeed_city',**configured}, enabled


def region_location(prefix, regions):
    label = f'NetBox prefix {record_id(prefix)}'
    if prefix.get('scope_type') != 'dcim.region' or prefix.get('scope_id') is None:
        raise GeofeedError(f'{label} needs a Region scope in region_hierarchy mode')
    sid = record_id({'id':prefix['scope_id']})
    embedded = prefix.get('scope')
    if embedded is not None and (not isinstance(embedded, dict) or str(embedded.get('id')) != sid):
        raise GeofeedError(f'{label} has conflicting Region scope references')
    chain, seen = [], set()
    current = sid
    while current is not None:
        if current in seen:
            raise GeofeedError(f'{label} Region hierarchy contains a cycle')
        if current not in regions:
            raise GeofeedError(f'{label} Region hierarchy has a missing parent or scope record')
        seen.add(current); row = regions[current]; chain.append(row)
        if len(chain) > 3:
            raise GeofeedError(f'{label} Region hierarchy must have exactly country/state/city levels')
        parent = row.get('parent')
        if parent is None:
            current = None
        elif isinstance(parent, dict) and record_id(parent) != '(unknown ID)':
            current = record_id(parent)
        else:
            raise GeofeedError(f'{label} Region hierarchy has an invalid parent reference')
    if len(chain) != 3:
        raise GeofeedError(f'{label} Region hierarchy must have exactly country/state/city levels')
    values = validate_location({'country':chain[2].get('name'),'region':chain[1].get('name'),
                                'city':chain[0].get('name')}, COARSE_FIELDS)
    return 'region:'+sid, values


def alternate_locations(prefixes, pages, mode, fields, enabled):
    regions = {str(row['id']):row for row in pages('/dcim/regions/')} if mode == 'region_hierarchy' else {}
    sites, resolved = {}, {}
    for prefix in prefixes:
        pid = str(prefix['id']); label = f'NetBox prefix {record_id(prefix)}'
        try:
            if mode == 'prefix_fields':
                custom = prefix.get('custom_fields')
                if custom is None:
                    custom = {}
                if not isinstance(custom, dict):
                    raise GeofeedError(f'{label} has invalid custom_fields')
                if enabled and custom.get(enabled) is not True:
                    raise GeofeedError(f'{label} geolocation flag is disabled, missing or not a boolean true')
                values = {}
                for key, name in fields.items():
                    value = custom.get(name)
                    values[key] = value.get('value') if isinstance(value, dict) else value
                sid = 'prefix:'+pid
            else:
                sid, values = region_location(prefix, regions)
            address = {'id':sid,'country':values['country'],'subdivision':values['region'],'city':values['city']}
            sites[sid] = {'id':sid,'name':sid,'addresses':[address]}
            resolved[pid] = (sid, None)
        except GeofeedError as exc:
            resolved[pid] = (None, f'{label} location could not be resolved: {exc}')
    return list(sites.values()), resolved
