"""Saved registry response formats share one normalization boundary."""
from .client import GeofeedError

INPUT_FORMATS = ('normalized', 'ripe-rest', 'rdap')


def normalize_input(data, input_format, observed_at):
    if input_format == 'normalized':
        return data, {}
    if input_format == 'ripe-rest':
        from .registry_ripe import normalize_ripe
        return normalize_ripe(data, observed_at), {'registry_source': 'RIPE'}
    if input_format == 'rdap':
        from .registry_rdap import normalize_rdap
        return normalize_rdap(data, observed_at)
    raise GeofeedError('Unsupported saved registry input format')
