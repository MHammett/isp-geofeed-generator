"""Publish with compare-and-swap and read back the unauthenticated public URL."""
import base64
import json
import os
import tempfile
import re
from . import __version__
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request
from .client import GeofeedError, JsonHTTP, https_url
from .feed import change_guard, digest, parse_feed


def atomic_write(path, data, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.chmod(name, mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class WordPress:
    def __init__(self, url, username, password, http=None):
        if not username or not password or ":" in username:
            raise GeofeedError("Set WP_USERNAME and WP_APP_PASSWORD")
        self.base = https_url(url) + "/wp-json/isp-geofeed-generator/v1"
        self.http = http or JsonHTTP(max_bytes=4_000_000)
        token = base64.b64encode((username + ":" + password).encode()).decode()
        self.headers = {"Authorization": "Basic " + token}

    @property
    def public_url(self):
        return self.base + "/feed"

    def state(self):
        try:
            result = self.http.request(self.base + "/state", headers=self.headers)
        except GeofeedError as exc:
            match = re.match(r'HTTP (401|403)\b', str(exc))
            if match:
                raise GeofeedError(f'WordPress state access refused (HTTP {match[1]}). Check application password, publisher permissions and Authorization header forwarding. Behind a trusted TLS proxy, WordPress must recognize the request as HTTPS') from None
            raise
        try:
            csv = result["csv"].encode("utf-8")
            if result["sha256"] != digest(csv):
                raise ValueError()
            if csv:
                parse_feed(csv)
            return csv
        except (KeyError, TypeError, AttributeError, ValueError):
            raise GeofeedError("WordPress state response is invalid") from None

    def replace(self, csv, expected):
        result = self.http.request(self.public_url, headers=self.headers,
            body={"csv": csv.decode("utf-8"), "expected_sha256": digest(expected)},
            method="PUT" if csv else "DELETE")
        if not isinstance(result, dict) or result.get("sha256") != digest(csv):
            raise GeofeedError("WordPress did not confirm the expected feed hash")

    def read_public(self):
        req = Request(self.public_url, headers={"User-Agent": "isp-geofeed-generator/" + __version__, "Cache-Control": "no-cache"})
        try:
            with self.http.opener.open(req, timeout=self.http.timeout) as response:
                data = response.read(1_000_001)
                if response.headers.get_content_type() not in ("text/csv", "text/plain"):
                    raise GeofeedError("Public feed has the wrong content type")
                parse_feed(data)
                return data
        except HTTPError as exc:
            exc.close()
            if exc.code == 404:
                return b""
            raise GeofeedError(f"Public feed HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError):
            raise GeofeedError("Cannot read the unauthenticated public feed") from None


def publish_wordpress(publisher, csv, state_dir, *, max_removed_fraction=0.10):
    try:
        old = publisher.state()
    except GeofeedError as exc:
        raise GeofeedError(f'WordPress preflight failed before any write: {exc}') from None
    change_guard(old, csv, max_removed_fraction)
    state_dir = Path(state_dir)
    atomic_write(state_dir / "before.csv", old)
    if old == csv:
        if publisher.read_public() != csv:
            raise GeofeedError("Stored feed matches but public feed differs; investigate WordPress/cache")
        return {"changed": False, "sha256": digest(csv), "url": publisher.public_url}
    try:
        publisher.replace(csv, old)
        if publisher.read_public() != csv:
            raise GeofeedError("Public read-back differs from generated feed")
    except GeofeedError as exc:
        # A lost PUT response may still have committed. Inspect, never blindly retry.
        try:
            observed = publisher.state()
            if observed == csv:
                publisher.replace(old, csv)
                if publisher.read_public() != old:
                    raise GeofeedError("Rollback read-back failed")
            elif observed != old:
                raise GeofeedError("Feed changed concurrently; refusing to overwrite it")
        except GeofeedError as rollback_error:
            raise GeofeedError(f"Publish failed: {exc}. Recovery needs attention: {rollback_error}") from None
        raise GeofeedError(f"Publish failed: {exc}. Previous feed retained/restored") from None
    atomic_write(state_dir / "last-good.csv", csv)
    return {"changed": True, "sha256": digest(csv), "url": publisher.public_url}


def publish_file(path, csv, state_dir, *, max_removed_fraction=0.10):
    target = Path(path)
    old = target.read_bytes() if target.exists() else b""
    change_guard(old, csv, max_removed_fraction)
    atomic_write(Path(state_dir) / "before.csv", old)
    if old != csv:
        atomic_write(target, csv, 0o644)
    if target.read_bytes() != csv:
        atomic_write(target, old, 0o644)
        raise GeofeedError("Local read-back failed; restored previous bytes")
    return {"changed": old != csv, "sha256": digest(csv), "path": str(target)}
