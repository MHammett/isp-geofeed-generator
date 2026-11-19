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
from .billmax import BillMax, validate_settings as validate_billmax
from .infoblox_nios import InfobloxNIOS, validate_settings as validate_nios
from .openwisp import OpenWISP, validate_settings as validate_openwisp
from .bluecat_bam import BlueCatBAM, validate_settings as validate_bluecat
from .publish import WordPress, publish_file, publish_wordpress
from .locations import LOCATION_FIELDS
from .credentials import InputCredentialStore
from .overlap import OVERLAP_POLICIES


def source_url(credentials, environment_name, default=''):
    """Use the named input endpoint; retain environment setup for legacy runs."""
    if isinstance(credentials, InputCredentialStore):
        return credentials.url or default
    return os.environ.get(environment_name, default)


def phpipam_source(settings, credentials):
    app_id = settings.get('app_id')
    if app_id is None:
        app_id = '' if isinstance(credentials, InputCredentialStore) else os.environ.get('PHPIPAM_APP_ID', '')
    return PhpIPAM(source_url(credentials, 'PHPIPAM_URL'), app_id,
                  credentials.get('PHPIPAM_API_TOKEN'), settings)


def billmax_source(settings, credentials):
    validate_billmax(settings)
    login = {}
    if settings.get('auth_mode') == 'userpass':
        login = {'username': credentials.get('BILLMAX_USERNAME'), 'password': credentials.get('BILLMAX_PASSWORD')}
    return BillMax(source_url(credentials, 'BILLMAX_URL'), credentials.get('BILLMAX_API_KEY'), settings, **login)


def validate_settings(kind, settings):
    """Built-in rules stay with their adapter metadata, not in the CLI."""
    lists = {'netbox': ('prefix_ids', 'range_ids', 'statuses', 'vrf_ids'),
             'splynx': ('network_ids',), 'phpipam': ('subnet_ids',)}
    for key in lists.get(kind, ()):
        if key in settings and not isinstance(settings[key], list):
            raise GeofeedError(f'source.{key} must be a list')
    if kind == 'netbox':
        from .netbox_locations import location_settings
        location_settings(settings)
        if settings.get('tag') and (settings.get('prefix_ids') or settings.get('range_ids')):
            raise GeofeedError('Choose a NetBox tag or explicit IDs, not both')
        if 'allow_http' in settings and not isinstance(settings['allow_http'], bool):
            raise GeofeedError('source.allow_http must be true or false')
        fields = settings.get('location_fields', {})
        if not isinstance(fields, dict) or set(fields) - {'country', 'region', 'city'}:
            raise GeofeedError('source.location_fields supports country, region and city')
    if kind == 'sonar' and settings.get('site_resolution', 'configured') not in ('configured', 'controllers'):
        raise GeofeedError('Sonar site_resolution must be configured or controllers')
    if kind == 'sonar':
        for key in ('pool_ids', 'subnet_ids'):
            Sonar.selected_ids(settings, key)
    if kind == 'splynx' and not isinstance(settings.get('location_sites', {}), dict):
        raise GeofeedError('source.location_sites must be a mapping')
    if kind == 'phpipam':
        PhpIPAM.location_settings(settings)


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


@dataclass
class RecordFileTarget:
    path: str

    def publish(self, records, state_dir, **guards):
        if not self.path:
            raise GeofeedError('JSON target needs publish.path')
        from .records import publish_records_file
        return publish_records_file(self.path, records, state_dir, **guards)


# Factories read only the credentials needed by that adapter. No configuration
# value is treated as an import path, executable command or arbitrary plugin.
SOURCES = {
    "bluecat_bam": SourceAdapter(lambda s, c: BlueCatBAM(source_url(c, 'BLUECAT_BAM_URL'), c.get('BLUECAT_BAM_USERNAME'), c.get('BLUECAT_BAM_API_TOKEN'), s),
        initial=True, settings=frozenset({'configuration_id', 'network_ids'}), validate=validate_bluecat),
    "openwisp": SourceAdapter(lambda s, c: OpenWISP(source_url(c, 'OPENWISP_URL'), c.get('OPENWISP_API_TOKEN'), s),
        initial=True, settings=frozenset({'organization_id', 'subnet_ids'}), validate=validate_openwisp),
    "infoblox_nios": SourceAdapter(lambda s, c: InfobloxNIOS(source_url(c, 'INFOBLOX_NIOS_URL'), c.get('INFOBLOX_NIOS_USERNAME'), c.get('INFOBLOX_NIOS_PASSWORD'), s),
        initial=True, settings=frozenset({'network_refs', 'location_fields'}), validate=validate_nios),
    "billmax": SourceAdapter(billmax_source, initial=True, settings=frozenset({'ap_ids', 'auth_mode'}), validate=validate_billmax),
    "sonar": SourceAdapter(lambda s, c: Sonar(source_url(c, "SONAR_URL"), c.get("SONAR_API_TOKEN"), settings=s), initial=False,
                           settings=frozenset({"site_resolution", "pool_ids", "subnet_ids"}), validate=lambda s: validate_settings('sonar', s)),
    "netbox": SourceAdapter(lambda s, c: NetBox(source_url(c, "NETBOX_URL"), c.get("NETBOX_API_TOKEN"), s), initial=False,
                            settings=frozenset({"allow_http", "auth_scheme", "tag", "prefix_ids", "range_ids", "statuses", "vrf_ids", "location_fields", "location_mode", "location_enabled_field"}), validate=lambda s: validate_settings('netbox', s)),
    "splynx": SourceAdapter(lambda s, c: Splynx(source_url(c, "SPLYNX_URL"), c.get("SPLYNX_API_KEY"), c.get("SPLYNX_API_SECRET"), s), initial=True,
                            settings=frozenset({"network_ids", "location_sites"}), validate=lambda s: validate_settings('splynx', s)),
    "phpipam": SourceAdapter(phpipam_source, initial=True,
                             settings=frozenset({"subnet_ids", "app_id", "location_mode", "facility_ids"}), validate=lambda s: validate_settings('phpipam', s)),
    "powercode": SourceAdapter(lambda s, c: Powercode(source_url(c, "POWERCODE_URL"), c.get("POWERCODE_API_KEY"), s), initial=True,
                               settings=frozenset({"range_ids", "facility_ids"})),
    "gaiia": SourceAdapter(lambda s, c: Gaiia(source_url(c, "GAIIA_URL", "https://api.gaiia.com/api/v1"), c.get("GAIIA_API_KEY"), s), initial=True,
                           settings=frozenset({"site_ids", "block_ids", "include_coordinates"})),
}

TARGETS = {
    "file": TargetAdapter(lambda s, c: FileTarget(s.get("path", "")), initial=False, settings=frozenset({'path'}),
                          api_version=2,overlap_policies=OVERLAP_POLICIES),
    "wordpress": TargetAdapter(lambda s, c: WordPressTarget(WordPress(os.environ.get("WP_SITE_URL", ""), os.environ.get("WP_USERNAME", ""), c.get("WP_APP_PASSWORD"))),
                               initial=False,api_version=2,overlap_policies=OVERLAP_POLICIES),
    "json": TargetAdapter(lambda s, c: RecordFileTarget(s.get('path', '')), settings=frozenset({'path'}),
                          payload_format='records', location_fields=LOCATION_FIELDS, required_fields=frozenset(),
                          api_version=2,overlap_policies=OVERLAP_POLICIES),
}
