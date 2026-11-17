"""Publish with compare-and-swap and read back the unauthenticated public URL."""
import base64
import json
import os
import tempfile
import re
import secrets
from . import __version__
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request
from .client import GeofeedError, JsonHTTP, https_url
from .feed import change_guard, digest, parse_feed


def atomic_write(path, data, mode=0o600, *, before_replace=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.chmod(name, mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if before_replace is not None:
            before_replace()
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class WordPress:
    def __init__(self, url, username, password, http=None):
        if not username or not password or ":" in username:
            raise GeofeedError("Set WP_USERNAME and WP_APP_PASSWORD")
        self.base = https_url(url) + "/wp-json/isp-geofeed-generator/v1"
        # State includes both 1 MB feeds; JSON Unicode escaping can triple their size.
        self.http = http or JsonHTTP(max_bytes=8_000_000)
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
            if ('overlap_policy' in result or 'required_overlap_policy' in result) and (
                    result.get('overlap_policy')!='reject' or result.get('required_overlap_policy')!='reject'):
                from .wordpress_policy import PolicyMismatch
                raise PolicyMismatch('WordPress state uses a different overlap policy; check the paired runner and plugin configuration before publishing')
            csv = result["csv"].encode("utf-8")
            if result["sha256"] != digest(csv):
                raise ValueError()
            if csv:
                parse_feed(csv)
            return csv
        except (KeyError, TypeError, AttributeError, ValueError):
            raise GeofeedError("WordPress state response is invalid") from None

    def replace(self, csv, expected):
        try:
            result = self.http.request(self.public_url, headers=self.headers,
                body={"csv": csv.decode("utf-8"), "expected_sha256": digest(expected)},
                method="PUT" if csv else "DELETE")
        except GeofeedError as exc:
            if re.match(r'HTTP 413\b', str(exc)):
                raise GeofeedError('WordPress upload refused (HTTP 413). Check request-body limits at the CDN, proxy, web server and PHP; JSON can be larger than the CSV. No retry was made') from None
            if re.match(r'HTTP 503\b', str(exc)):
                raise GeofeedError('WordPress write unavailable (HTTP 503). State may already have committed. Check configured delivery hooks, server/database logs and max_allowed_packet; HTTP status alone does not identify the cause. No retry was made') from None
            raise
        if not isinstance(result, dict) or result.get("sha256") != digest(csv):
            raise GeofeedError("WordPress did not confirm the expected feed hash")

    def policy_state(self):
        from .wordpress_policy import read_state
        return read_state(self)

    def replace_policy(self,csv,policy,expected,publication_id,operation='publish'):
        from .wordpress_policy import replace
        return replace(self,csv,policy,expected,publication_id,operation)

    def configure_policy(self,policy,expected,publication_id):
        from .wordpress_policy import configure_request
        return configure_request(self,policy,expected,publication_id)

    def read_public(self, *, overlap_policy='reject'):
        return self._read_public(self.public_url, overlap_policy)

    def read_public_probe(self, *, overlap_policy='reject'):
        # One anonymous diagnostic GET on the same fixed route. A fresh cache key
        # is not proof that the response reached origin or refreshed the normal URL.
        return self._read_public(self.public_url + '?isp_geofeed_probe=' + secrets.token_hex(16), overlap_policy)

    def _read_public(self, url, overlap_policy):
        req = Request(url, headers={"User-Agent": "isp-geofeed-generator/" + __version__, "Cache-Control": "no-cache"})
        try:
            with self.http.opener.open(req, timeout=self.http.timeout) as response:
                data = response.read(1_000_001)
                if response.headers.get_content_type() not in ("text/csv", "text/plain"):
                    raise GeofeedError("Public feed has the wrong content type")
                parse_feed(data,overlap_policy=overlap_policy)
                return data
        except HTTPError as exc:
            exc.close()
            if exc.code == 404:
                return b""
            raise GeofeedError(f"Public feed HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError):
            raise GeofeedError("Cannot read the unauthenticated public feed") from None


def publish_wordpress(publisher, csv, state_dir, *, max_removed_fraction=0.10, max_relocated_fraction=0.10, overlap_policy='reject'):
    from .overlap import validate_policy,LONGEST_PREFIX
    validate_policy(overlap_policy)
    if overlap_policy==LONGEST_PREFIX:
        from .wordpress_policy import publish
        return publish(publisher,csv,state_dir,max_removed_fraction,max_relocated_fraction)
    try:
        old = publisher.state()
    except GeofeedError as exc:
        from .wordpress_policy import PolicyMismatch,publish
        if isinstance(exc,PolicyMismatch):
            return publish(publisher,csv,state_dir,max_removed_fraction,max_relocated_fraction,desired=overlap_policy)
        raise GeofeedError(f'WordPress preflight failed before any write: {exc}') from None
    change_guard(old, csv, max_removed_fraction, max_relocated_fraction=max_relocated_fraction)
    state_dir = Path(state_dir)
    if publisher.read_public() != old:
        raise GeofeedError('WordPress stored state and public feed differ; no write attempted; investigate cache, routing or another publisher')
    if old == csv:
        if publisher.state() != old:
            raise GeofeedError('WordPress state changed during unchanged-content verification; no write attempted')
        return {"changed": False, "sha256": digest(csv), "url": publisher.public_url,
                'verification': 'authenticated-and-public', 'recovery_backup_changed': False}
    atomic_write(state_dir / "before.csv", old)
    try:
        publisher.replace(csv, old)
        if publisher.read_public() != csv:
            raise GeofeedError("Public read-back differs from generated feed")
        if publisher.state() != csv:
            raise GeofeedError('WordPress authenticated state changed after public read-back')
    except GeofeedError as exc:
        # A lost PUT response may still have committed. Inspect, never blindly retry.
        try:
            observed = publisher.state()
            if observed == csv:
                publisher.replace(old, csv)
                if publisher.read_public() != old:
                    raise GeofeedError("Rollback read-back failed")
                if publisher.state() != old:
                    raise GeofeedError('Rollback authenticated state differs')
            elif observed != old:
                raise GeofeedError("Feed changed concurrently; refusing to overwrite it")
            elif publisher.read_public() != old:
                raise GeofeedError('Previous stored feed remains but its public delivery could not be verified')
        except GeofeedError as rollback_error:
            raise GeofeedError(f"Publish failed: {exc}. Recovery needs attention: {rollback_error}") from None
        raise GeofeedError(f"Publish failed: {exc}. Previous feed retained/restored") from None
    atomic_write(state_dir / "last-good.csv", csv)
    return {"changed": True, "sha256": digest(csv), "url": publisher.public_url,
            'verification': 'authenticated-and-public', 'recovery_backup_changed': True}


def publish_file(path, csv, state_dir, *, max_removed_fraction=0.10, max_relocated_fraction=0.10, overlap_policy='reject'):
    from .overlap import validate_policy, LONGEST_PREFIX
    validate_policy(overlap_policy)
    if overlap_policy == LONGEST_PREFIX:
        from .bound_output import publish_bound
        def validate(old,new,old_policy):
            change_guard(old,new,max_removed_fraction,max_relocated_fraction=max_relocated_fraction,
                         overlap_policy=overlap_policy,old_overlap_policy=old_policy)
        changed=publish_bound(path,csv,state_dir,'csv',validate,1_000_000)
        return {'changed':changed,'sha256':digest(csv),'path':str(Path(path)),
                'overlap_policy':overlap_policy,'verification':'local-bytes-and-policy','recovery_backup_changed':changed}
    from .local_output import publish_local
    def validate(old, new):
        change_guard(old, new, max_removed_fraction, max_relocated_fraction=max_relocated_fraction)
    changed = publish_local(path, csv, state_dir, 'before.csv', validate, 1_000_000)
    return {"changed": changed, "sha256": digest(csv), "path": str(Path(path)),
            'verification': 'local-bytes', 'recovery_backup_changed': changed}
