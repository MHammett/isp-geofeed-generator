"""Independent input and output registries. Entries are trusted local code."""
import os
from dataclasses import dataclass
from typing import Callable, Protocol
from .client import GeofeedError, Sonar
from .netbox import NetBox
from .splynx import Splynx
from .phpipam import PhpIPAM
from .publish import WordPress, publish_file, publish_wordpress


class Source(Protocol):
    def snapshot(self) -> dict: ...
    def for_publication(self, snapshot: dict) -> dict: ...


class Target(Protocol):
    def publish(self, csv: bytes, state_dir, **guards) -> dict: ...


@dataclass(frozen=True)
class SourceAdapter:
    create: Callable
    initial: bool = False
    settings: frozenset = frozenset()


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
    "sonar": SourceAdapter(lambda s, c: Sonar(os.environ.get("SONAR_URL", ""), c.get("SONAR_API_TOKEN"), settings=s),
                           settings=frozenset({"site_resolution"})),
    "netbox": SourceAdapter(lambda s, c: NetBox(os.environ.get("NETBOX_URL", ""), c.get("NETBOX_API_TOKEN"), s),
                            settings=frozenset({"allow_http", "auth_scheme", "tag", "prefix_ids", "range_ids", "statuses", "vrf_ids", "location_fields"})),
    "splynx": SourceAdapter(lambda s, c: Splynx(os.environ.get("SPLYNX_URL", ""), c.get("SPLYNX_API_KEY"), c.get("SPLYNX_API_SECRET"), s), initial=True,
                            settings=frozenset({"network_ids", "location_sites"})),
    "phpipam": SourceAdapter(lambda s, c: PhpIPAM(os.environ.get("PHPIPAM_URL", ""), os.environ.get("PHPIPAM_APP_ID", ""), c.get("PHPIPAM_API_TOKEN"), s), initial=True,
                             settings=frozenset({"subnet_ids"})),
}

TARGETS = {
    "file": lambda s, c: FileTarget(s.get("path", "")),
    "wordpress": lambda s, c: WordPressTarget(WordPress(os.environ.get("WP_SITE_URL", ""), os.environ.get("WP_USERNAME", ""), c.get("WP_APP_PASSWORD"))),
}
