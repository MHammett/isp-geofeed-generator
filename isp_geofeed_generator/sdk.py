"""Supported imports for separately installed, operator-enabled extensions."""
from .contracts import ADAPTER_API_VERSION, TARGET_API_VERSION, SourceAdapter, TargetAdapter, Source, Target
from .client import GeofeedError, JsonHTTP, https_url
from .publish import publish_file, publish_wordpress, atomic_write
from .locations import LOCATION_FIELDS, COARSE_FIELDS
from .records import publish_records_file
from .adapters import source_url
from .relocation import relocation_guard, effective_change_guard
from .overlap import REJECT, LONGEST_PREFIX, require_target_policy
from .bound_output import recover_bound as recover_local

__all__ = ['ADAPTER_API_VERSION', 'TARGET_API_VERSION', 'REJECT', 'LONGEST_PREFIX', 'require_target_policy', 'SourceAdapter', 'TargetAdapter', 'Source', 'Target',
           'GeofeedError', 'JsonHTTP', 'https_url', 'publish_file', 'publish_wordpress', 'atomic_write',
           'builtin_source', 'builtin_target', 'LOCATION_FIELDS', 'COARSE_FIELDS', 'publish_records_file', 'source_url', 'relocation_guard', 'effective_change_guard', 'recover_local']


def builtin_source(name, settings, credentials):
    """Construct a shipped source for a local wrapper without patching its code."""
    from .adapters import SOURCES
    if name not in SOURCES:
        raise GeofeedError('Unknown built-in source requested by extension')
    adapter = SOURCES[name]
    if set(settings) - ({'type', 'allow_initial'} | adapter.settings):
        raise GeofeedError('Unknown built-in source settings in extension wrapper')
    if adapter.validate is not None:
        adapter.validate(settings)
    return adapter.create(settings, credentials)


def builtin_target(name, settings, credentials):
    """Construct a shipped output for a local wrapper."""
    from .adapters import TARGETS
    if name not in TARGETS:
        raise GeofeedError('Unknown built-in target requested by extension')
    adapter = TARGETS[name]
    if set(settings) - ({'type', 'allow_initial', 'location_fields'} | adapter.settings):
        raise GeofeedError('Unknown built-in target settings in extension wrapper')
    return adapter(settings, credentials)
