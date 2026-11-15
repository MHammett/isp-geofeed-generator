import argparse
import json
import importlib
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import yaml
from .client import GeofeedError, Sonar
from .netbox import NetBox
from .credentials import CredentialStore
from .feed import build, digest
from .publish import WordPress, atomic_write, publish_file, publish_wordpress


def shared_module(name):
    path = os.environ.get("SCRIPTING_COMMON_PATH")
    if not path:
        return None
    if path not in sys.path:
        sys.path.insert(0, path)
    try:
        return importlib.import_module(name)
    except ImportError:
        raise GeofeedError(f"Configured scripting-common module {name} is unavailable") from None


def load_config(path):
    try:
        config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        raise GeofeedError("Cannot read YAML configuration") from None
    if not isinstance(config, dict):
        raise GeofeedError("Configuration must be a YAML mapping")
    allowed = {"source", "credentials", "allowed_prefixes", "pool_sites", "exclude_pools", "site_locations", "publish", "state_dir", "max_removed_fraction"}
    if set(config) - allowed:
        raise GeofeedError("Unknown configuration keys: " + ", ".join(sorted(set(config) - allowed)))
    limit = config.get("max_removed_fraction", 0.10)
    if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not 0 <= limit <= 1:
        raise GeofeedError("max_removed_fraction must be between 0 and 1")
    for name in ("pool_sites", "exclude_pools", "site_locations", "publish"):
        if not isinstance(config.get(name, {}), dict):
            raise GeofeedError(f"{name} must be a YAML mapping")
    if not isinstance(config.get("allowed_prefixes", []), list):
        raise GeofeedError("allowed_prefixes must be a list")
    source = config.get("source", {"type": "sonar"})
    if not isinstance(source, dict) or source.get("type") not in ("sonar", "netbox", "splynx", "phpipam"):
        raise GeofeedError("source.type must be sonar, netbox, splynx or phpipam")
    source_keys = {"type", "allow_http", "auth_scheme", "tag", "prefix_ids", "range_ids", "statuses", "vrf_ids", "location_fields",
                   "site_resolution", "network_ids", "location_sites", "subnet_ids", "allow_initial"}
    if set(source) - source_keys:
        raise GeofeedError("Unknown source configuration keys")
    if source.get("tag") and (source.get("prefix_ids") or source.get("range_ids")):
        raise GeofeedError("Choose a NetBox tag or explicit IDs, not both")
    if "allow_http" in source and not isinstance(source["allow_http"], bool):
        raise GeofeedError("source.allow_http must be true or false")
    for key in ("prefix_ids", "range_ids", "statuses", "vrf_ids", "network_ids", "subnet_ids"):
        if key in source and not isinstance(source[key], list):
            raise GeofeedError(f"source.{key} must be a list")
    if not isinstance(source.get("location_fields", {}), dict) or set(source.get("location_fields", {})) - {"country", "region", "city"}:
        raise GeofeedError("source.location_fields supports country, region and city")
    CredentialStore(config.get("credentials"))
    if source.get("site_resolution", "configured") not in ("configured", "controllers"):
        raise GeofeedError("Sonar site_resolution must be configured or controllers")
    if not isinstance(source.get("location_sites", {}), dict):
        raise GeofeedError("source.location_sites must be a mapping")
    if "allow_initial" in source and not isinstance(source["allow_initial"], bool):
        raise GeofeedError("source.allow_initial must be true or false")
    return config


@contextmanager
def run_lock(directory):
    """Cross-platform OS lock; it is released automatically on process exit."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    shared = shared_module("lockfile")
    if shared is not None:
        with shared.LockFile(str(directory / "run.lock")) as lock:
            if not lock.held:
                raise GeofeedError("Another run is active")
            yield
        return
    with (directory / "run.lock").open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise GeofeedError("Another run is active") from None
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise GeofeedError("Another run is active") from None
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def status(directory, result):
    shared = shared_module("status")
    if shared is not None:
        if not shared.StatusWriter("isp-geofeed-generator", Path(directory) / "status.json").write(result):
            raise GeofeedError("Could not save publication status")
        return
    value = {"tool": "isp-geofeed-generator", "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), "data": result}
    atomic_write(Path(directory) / "status.json", json.dumps(value, indent=2).encode())


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read Sonar or NetBox IPAM and publish a coarse-location geofeed")
    parser.add_argument("command", choices=("discover", "generate", "publish"))
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--output", help="Private discovery JSON or candidate CSV output file")
    parser.add_argument("--assignment-candidates", action="store_true", help="Discover observed pool use on site equipment; does not choose a host")
    parser.add_argument("--controller-candidates", action="store_true", help="Discover Sonar controller management-IP site links")
    args = parser.parse_args(argv)
    directory = None
    credentials = CredentialStore()
    try:
        config = load_config(args.config)
        credentials = CredentialStore(config.get("credentials"))
        directory = Path(config.get("state_dir", "state"))
        with run_lock(directory):
            source_kind = config.get("source", {}).get("type", "sonar")
            if source_kind == "netbox":
                source = NetBox(os.environ.get("NETBOX_URL", ""), credentials.get("NETBOX_API_TOKEN"), config["source"])
            elif source_kind == "splynx":
                from .splynx import Splynx
                source = Splynx(os.environ.get("SPLYNX_URL", ""), credentials.get("SPLYNX_API_KEY"), credentials.get("SPLYNX_API_SECRET"), config["source"])
            elif source_kind == "phpipam":
                from .phpipam import PhpIPAM
                source = PhpIPAM(os.environ.get("PHPIPAM_URL", ""), os.environ.get("PHPIPAM_APP_ID", ""), credentials.get("PHPIPAM_API_TOKEN"), config["source"])
            else:
                source = Sonar(os.environ.get("SONAR_URL", ""), credentials.get("SONAR_API_TOKEN"), settings=config.get("source"))
            snapshot = source.snapshot()
            if args.command == "discover":
                if args.assignment_candidates:
                    if source_kind != "sonar":
                        raise GeofeedError("--assignment-candidates applies to Sonar; NetBox reports native scopes")
                    snapshot["assignment_candidates"] = source.assignment_candidates(snapshot["sites"])
                    snapshot["candidate_warning"] = "Observed address use is not proof of pool hosting or ownership. Review before mapping."
                if args.controller_candidates:
                    if source_kind != "sonar":
                        raise GeofeedError("--controller-candidates applies to Sonar")
                    snapshot["controller_candidates"] = source.controller_candidates(snapshot)
                data = (json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n").encode()
                if args.output:
                    atomic_write(args.output, data)
                else:
                    print(data.decode(), end="")
                return 0
            if source_kind != "sonar":
                snapshot = source.for_publication(snapshot)
            if args.command == "publish" and source_kind in ("splynx", "phpipam") and config["source"].get("allow_initial") is not True:
                raise GeofeedError("Initial adapter: run discovery and candidate checks, then explicitly set source.allow_initial: true before publishing")
            csv, report = build(snapshot, config)
            if args.command == "generate":
                if args.output:
                    atomic_write(args.output, csv)
                else:
                    sys.stdout.write(csv.decode())
                print(f"Validated {len(csv.splitlines())} prefixes; sha256={digest(csv)}", file=sys.stderr)
                return 0
            settings = config.get("publish", {})
            kwargs = {"max_removed_fraction": config.get("max_removed_fraction", 0.10)}
            if settings.get("type") == "wordpress":
                wp = WordPress(os.environ.get("WP_SITE_URL", ""), os.environ.get("WP_USERNAME", ""), credentials.get("WP_APP_PASSWORD"))
                result = publish_wordpress(wp, csv, directory, **kwargs)
            elif settings.get("type") == "file" and settings.get("path"):
                result = publish_file(settings["path"], csv, directory, **kwargs)
            else:
                raise GeofeedError("Choose publish.type wordpress or file (with path)")
            status(directory, {"healthy": True, **result, "pools": report})
            print(json.dumps(result))
        return 0
    except (GeofeedError, OSError, ValueError, TypeError, KeyError) as exc:
        # Configuration errors must never dump secrets or complete API responses.
        message = credentials.redact(str(exc)) if isinstance(exc, GeofeedError) else f"Local data/configuration error ({type(exc).__name__})"
        if directory is not None and args.command == "publish":
            try:
                status(directory, {"healthy": False, "error": message})
            except OSError:
                pass
        print("ERROR: " + message, file=sys.stderr)
        return 1
