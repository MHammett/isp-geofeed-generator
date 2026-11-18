"""Saved registry response formats share one normalization boundary."""
from .client import GeofeedError

INPUT_FORMATS = ('normalized', 'ripe-rest', 'rdap')


def rdap_options(input_format, rdap_language):
    if rdap_language is None:
        return {}
    if input_format != 'rdap':
        raise GeofeedError('--rdap-language requires --registry-format rdap; no input read or write attempted')
    from .rdap_language import language_tag
    return {'rdap_language': language_tag(rdap_language)}


def normalize_input(data, input_format, observed_at, *, rdap_language=None):
    options = rdap_options(input_format, rdap_language)
    if input_format == 'normalized':
        return data, {}
    if input_format == 'ripe-rest':
        from .registry_ripe import normalize_ripe
        return normalize_ripe(data, observed_at), {'registry_source': 'RIPE'}
    if input_format == 'rdap':
        from .registry_rdap import normalize_rdap
        return normalize_rdap(data, observed_at, **options)
    raise GeofeedError('Unsupported saved registry input format')
