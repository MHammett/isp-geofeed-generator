"""Mandatory fullbogon guard for every CLI-generated/published payload."""
import bisect
import ipaddress
import re
import time
from pathlib import Path
from urllib.request import Request, build_opener
from .client import GeofeedError, NoRedirects
from .publish import atomic_write

URLS = {v: f'https://www.team-cymru.org/Services/Bogons/fullbogons-ipv{v}.txt' for v in (4, 6)}
MAX_BYTES = 16_000_000
MAX_AGE = 86400
REFRESH_AFTER = 14400


class BogonIndex:
    def __init__(self, data, version, now=None):
        now = time.time() if now is None else now
        if not isinstance(data, bytes) or len(data) > MAX_BYTES:
            raise GeofeedError('Bogon data is missing or exceeds size limit')
        try:
            lines = data.decode('ascii').splitlines()
            match = re.fullmatch(r'# last updated ([0-9]{1,12})(?: \(.*\))?', lines[0])
            if not match:
                raise ValueError()
            self.updated = int(match[1])
            if now - self.updated > MAX_AGE or self.updated > now + 300:
                raise GeofeedError(f'IPv{version} bogon data is stale or has a future timestamp; publication stopped')
            intervals = []
            for line in lines[1:]:
                if not line.strip() or line.startswith('#'):
                    continue
                net = ipaddress.ip_network(line.strip(), strict=True)
                if net.version != version:
                    raise ValueError()
                intervals.append((int(net.network_address), int(net.broadcast_address)))
            if not intervals or len(intervals) > 500000:
                raise ValueError()
            intervals.sort()
            self.starts, self.ends = [], []
            for start, end in intervals:
                if self.ends and start <= self.ends[-1]:
                    raise ValueError()
                self.starts.append(start); self.ends.append(end)
            canaries = ('0.0.0.0/8', '10.0.0.0/8', '127.0.0.0/8', '224.0.0.0/4') if version == 4 else ('::/128', 'fc00::/7', 'ff00::/8')
            for value in canaries:
                net = ipaddress.ip_network(value)
                i = bisect.bisect_right(self.starts, int(net.network_address)) - 1
                if i < 0 or self.ends[i] < int(net.broadcast_address):
                    raise GeofeedError(f'IPv{version} bogon data failed reserved-space controls; no partial list accepted')
            self.version = version
        except (UnicodeError, ValueError, IndexError):
            raise GeofeedError(f'IPv{version} bogon list is malformed or incomplete') from None

    def overlaps(self, network):
        if network.version != self.version:
            return False
        i = bisect.bisect_right(self.starts, int(network.broadcast_address)) - 1
        return i >= 0 and self.ends[i] >= int(network.network_address)


class BogonPolicy:
    def __init__(self, indexes):
        self.indexes = indexes

    def check(self, networks):
        for net in networks:
            if self.indexes[net.version].overlaps(net):
                raise GeofeedError(f'Prefix {net} overlaps reserved or unallocated bogon space; output stopped')


def load_policy(config, *, fetch=None, now=None):
    now = time.time() if now is None else now
    settings = config.get('bogons', {})
    if not isinstance(settings, dict) or set(settings) - {'ipv4_file', 'ipv6_file'}:
        raise GeofeedError('bogons supports ipv4_file and ipv6_file only; exclusion cannot be disabled')
    if bool(settings.get('ipv4_file')) != bool(settings.get('ipv6_file')):
        raise GeofeedError('Configure both IPv4 and IPv6 bogon files')
    cache = Path(config.get('state_dir', 'state'))/'bogons'
    indexes = {}
    for version in (4, 6):
        local = settings.get(f'ipv{version}_file')
        if local:
            path = Path(local)
            if not path.is_absolute():
                raise GeofeedError('Bogon file paths must be absolute and outside the checkout')
            with path.open('rb') as stream:
                data = stream.read(MAX_BYTES + 1)
            indexes[version] = BogonIndex(data, version, now)
            continue
        path = cache/f'fullbogons-ipv{version}.txt'
        if path.exists():
            with path.open('rb') as stream:
                data = stream.read(MAX_BYTES + 1)
            try:
                index = BogonIndex(data, version, now)
            except GeofeedError:
                index = None
            if index is not None and now - path.stat().st_mtime < REFRESH_AFTER:
                indexes[version] = index
                continue
        try:
            if fetch is None:
                request = Request(URLS[version], headers={'User-Agent': 'isp-geofeed-generator-bogon-update'})
                with build_opener(NoRedirects()).open(request, timeout=30) as response:
                    data = response.read(MAX_BYTES + 1)
            else:
                data = fetch(version)
            index = BogonIndex(data, version, now)
        except Exception:
            raise GeofeedError(f'Cannot refresh validated IPv{version} bogon data; no retry or stale fallback was made') from None
        atomic_write(path, data)
        indexes[version] = index
    return BogonPolicy(indexes)
