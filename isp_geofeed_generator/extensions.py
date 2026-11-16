"""Load only explicitly enabled installed entry points, with no path imports."""
import re
from importlib import metadata
from .client import GeofeedError
from .contracts import ADAPTER_API_VERSION, SourceAdapter, TargetAdapter
from .locations import LOCATION_FIELDS
from .overlap import OVERLAP_POLICIES, REJECT


def load_extensions(settings, sources, targets):
    settings = {} if settings is None else settings
    if not isinstance(settings, dict) or set(settings) - {'sources', 'targets', 'targets_v2'}:
        raise GeofeedError('extensions supports sources, targets and targets_v2 lists only')
    result = (dict(sources), dict(targets))
    for kind, registry, cls, group, version in (
            ('sources', result[0], SourceAdapter, 'sources.v1', 1),
            ('targets', result[1], TargetAdapter, 'targets.v1', 1),
            ('targets_v2', result[1], TargetAdapter, 'targets.v2', 2)):
        names = settings.get(kind, [])
        if (not isinstance(names, list) or any(not isinstance(n, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', n) for n in names)
                or len(names) != len(set(names))):
            raise GeofeedError(f'extensions.{kind} must contain unique adapter names')
        # No metadata discovery or imports for disabled groups.
        if not names:
            continue
        entries = metadata.entry_points(group=f'isp_geofeed_generator.{group}')
        for name in names:
            if name in registry:
                raise GeofeedError(f'Extension {name} cannot replace a built-in adapter')
            matches = [e for e in entries if e.name == name]
            if len(matches) != 1:
                raise GeofeedError(f'Extension {name} is missing or ambiguous; check installed packages in this interpreter')
            try:
                adapter = matches[0].load()
            except Exception:
                raise GeofeedError(f'Extension {name} could not be imported; no raw extension error was logged') from None
            if (not isinstance(adapter, cls) or type(adapter.api_version) is not int or adapter.api_version != version
                    or type(adapter.initial) is not bool or not callable(adapter.create)
                    or not isinstance(adapter.settings, frozenset)
                    or any(not isinstance(k, str) or k in ({'type', 'allow_initial', 'location_fields'} if isinstance(adapter, TargetAdapter) else {'type', 'allow_initial'}) for k in adapter.settings)
                    or (isinstance(adapter, SourceAdapter) and adapter.validate is not None and not callable(adapter.validate))):
                raise GeofeedError(f'Extension {name} has an incompatible or invalid adapter contract')
            registry[name] = adapter
            if isinstance(adapter, TargetAdapter) and (
                    adapter.payload_format not in ('csv', 'records')
                    or not isinstance(adapter.location_fields, frozenset) or not isinstance(adapter.required_fields, frozenset)
                    or adapter.location_fields - LOCATION_FIELDS or adapter.required_fields - adapter.location_fields):
                raise GeofeedError(f'Extension {name} declares invalid location capabilities')
            if isinstance(adapter, TargetAdapter) and (
                    not isinstance(adapter.overlap_policies, frozenset) or not adapter.overlap_policies
                    or adapter.overlap_policies - OVERLAP_POLICIES
                    or (version == 1 and adapter.overlap_policies != frozenset({REJECT}))):
                raise GeofeedError(f'Extension {name} declares invalid overlap capabilities')
    return result
