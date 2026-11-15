"""Independent input and output registries. Entries are trusted local code."""
import os
from dataclasses import dataclass
from .contracts import SourceAdapter, TargetAdapter, Source, Target
from .client import GeofeedError, Sonar
from .netbox import NetBox
from .splynx import Splynx
from .phpipam import PhpIPAM
from .powercode import Powercode
from .gaiia import Gaiia
from .publish import WordPress, publish_file, publish_wordpress


def validate_settings(kind, settings):
    """Built-in rules stay with their adapter metadata, not in the CLI."""
    lists = {'netbox': ('prefix_ids', 'range_ids', 'statuses', 'vrf_ids'),
             'splynx': ('network_ids',), 'phpipam': ('subnet_ids',)}
    for key in lists.get(kind, ()):
        if key in settings and not isinstance(settings[key], list):
            raise GeofeedError(f'source.{key} must be a list')
    if kind == 'netbox':
        if settings.get('tag') and (settings.get('prefix_ids') or settings.get('range_ids')):
            raise GeofeedError('Choose a NetBox tag or explicit IDs, not both')
        if 'allow_http' in settings and not isinstance(settings['allow_http'], bool):
            raise GeofeedError('source.allow_http must be true or false')
        fields = settings.get('location_fields', {})
        if not isinstance(fields, dict) or set(fields) - {'country', 'region', 'city'}:
            raise GeofeedError('source.location_fields supports country, region and city')
    if kind == 'sonar' and settings.get('site_resolution', 'configured') not in ('configured', 'controllers'):
        raise GeofeedError('Sonar site_resolution must be configured or controllers')
    if kind == 'splynx' and not isinstance(settings.get('location_sites', {}), dict):
        raise GeofeedError('source.location_sites must be a mapping')


@dataclass
class FileTarget:
    path: str

    def publish(self, csv, state_dir, **guards):
        if not self.path:
            raise GeofeedError("File target needs publish.path")
        return publish_file(self.path, csv, state_dir, **guards)


@dataclass
class WordPressTarget:
    client: WordPress

    def publish(self, csv, state_dir, **guards):
        return publish_wordpress(self.client, csv, state_dir, **guards)


# Factories read only the credentials needed by that adapter. No configuration
# value is treated as an import path, executable command or arbitrary plugin.
SOURCES = {
    "sonar": SourceAdapter(lambda s, c: Sonar(os.environ.get("SONAR_URL", ""), c.get("SONAR_API_TOKEN"), settings=s), initial=False,
                           settings=frozenset({"site_resolution"}), validate=lambda s: validate_settings('sonar', s)),
    "netbox": SourceAdapter(lambda s, c: NetBox(os.environ.get("NETBOX_URL", ""), c.get("NETBOX_API_TOKEN"), s), initial=False,
                            settings=frozenset({"allow_http", "auth_scheme", "tag", "prefix_ids", "range_ids", "statuses", "vrf_ids", "location_fields"}), validate=lambda s: validate_settings('netbox', s)),
    "splynx": SourceAdapter(lambda s, c: Splynx(os.environ.get("SPLYNX_URL", ""), c.get("SPLYNX_API_KEY"), c.get("SPLYNX_API_SECRET"), s), initial=True,
                            settings=frozenset({"network_ids", "location_sites"}), validate=lambda s: validate_settings('splynx', s)),
    "phpipam": SourceAdapter(lambda s, c: PhpIPAM(os.environ.get("PHPIPAM_URL", ""), os.environ.get("PHPIPAM_APP_ID", ""), c.get("PHPIPAM_API_TOKEN"), s), initial=True,
                             settings=frozenset({"subnet_ids"}), validate=lambda s: validate_settings('phpipam', s)),
    "powercode": SourceAdapter(lambda s, c: Powercode(os.environ.get("POWERCODE_URL", ""), c.get("POWERCODE_API_KEY"), s), initial=True,
                               settings=frozenset({"range_ids", "facility_ids"})),
    "gaiia": SourceAdapter(lambda s, c: Gaiia(os.environ.get("GAIIA_URL", "https://api.gaiia.com/api/v1"), c.get("GAIIA_API_KEY"), s), initial=True,
                           settings=frozenset({"site_ids", "block_ids"})),
}

TARGETS = {
    "file": TargetAdapter(lambda s, c: FileTarget(s.get("path", "")), initial=False, settings=frozenset({'path'})),
    "wordpress": TargetAdapter(lambda s, c: WordPressTarget(WordPress(os.environ.get("WP_SITE_URL", ""), os.environ.get("WP_USERNAME", ""), c.get("WP_APP_PASSWORD"))), initial=False),
}
