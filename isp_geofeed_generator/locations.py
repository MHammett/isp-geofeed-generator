"""Typed location values, independent of provider wire formats."""
import math
import re
from .client import GeofeedError

COARSE_FIELDS = frozenset({'country', 'region', 'city'})
LOCATION_FIELDS = COARSE_FIELDS | {'latitude', 'longitude', 'postal_code', 'accuracy_km'}


def validate_location(value, fields):
    if not fields or set(fields) - LOCATION_FIELDS or not isinstance(value, dict):
        raise GeofeedError('Output location fields are missing or unsupported')
    if bool('latitude' in fields) != bool('longitude' in fields):
        raise GeofeedError('Latitude and longitude must be requested together')
    result = {}
    for field in ('country', 'region', 'city', 'latitude', 'longitude', 'postal_code', 'accuracy_km'):
        if field not in fields:
            continue
        data = value.get(field)
        if field == 'region' and data is None:
            data = ''
        if field in ('latitude', 'longitude', 'accuracy_km'):
            if isinstance(data, bool) or not isinstance(data, (int, float)) or not math.isfinite(data):
                raise GeofeedError(f'Location needs a finite numeric {field}')
            limit = 90 if field == 'latitude' else 180
            if (field == 'accuracy_km' and data < 0) or (field != 'accuracy_km' and not -limit <= data <= limit):
                raise GeofeedError(f'Location {field} is out of range')
        else:
            if not isinstance(data, str) or len(data) > 512 or any(ord(c) < 32 or ord(c) == 127 for c in data):
                raise GeofeedError(f'Location needs a valid {field}')
            data = data.strip()
            if field != 'region' and not data:
                raise GeofeedError(f'Location needs a nonempty {field}')
            if field == 'country' and not re.fullmatch(r'[A-Z]{2}', data):
                raise GeofeedError('Location country code is invalid or missing')
            if field == 'region' and data and not re.fullmatch(r'[A-Z]{2}-[A-Z0-9]{1,3}', data):
                raise GeofeedError('Location subdivision/region code is invalid')
        result[field] = data
    if result.get('country') and result.get('region') and not result['region'].startswith(result['country'] + '-'):
        raise GeofeedError('Location country and region disagree')
    return result


def project_site(site, override, fields):
    override = {} if override is None else override
    addresses = site.get('addresses', [])
    if not isinstance(override, dict) or not isinstance(addresses, list) or any(not isinstance(a, dict) for a in addresses):
        raise GeofeedError(f"Site {site['id']} has invalid location data")
    if override.get('address_id') is not None:
        addresses = [a for a in addresses if str(a.get('id')) == str(override['address_id'])]
    if len(addresses) != 1:
        raise GeofeedError(f"Site {site['id']} needs exactly one address, or an explicit address_id")
    values = {**addresses[0], 'region': addresses[0].get('subdivision'), **override}
    if isinstance(values.get('region'), str):
        values['region'] = values['region'].replace('_', '-')
    try:
        return validate_location(values, fields)
    except GeofeedError as exc:
        raise GeofeedError(f"Site {site['id']}: {exc}") from None
