import argparse
import json
import importlib
import os
import re
import sys
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
import yaml
from .client import GeofeedError
from .adapters import SOURCES, TARGETS
from .extensions import load_extensions
from .credentials import CredentialStore
from .feed import build_records, render_csv, digest
from .bogons import load_policy
from .locations import COARSE_FIELDS
import ipaddress
from .publish import atomic_write
from .inputs import validate_source, validate_inputs, read_inputs, combine_inputs


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


class LoadedConfig(dict):
    """Per-run registries are attributes, never serialized configuration keys."""
    def __init__(self, values, sources, targets):
        super().__init__(values)
        self.sources, self.targets = sources, targets


class UniqueKeyLoader(yaml.SafeLoader):
    """A repeated input or policy key must not silently replace an earlier one."""
    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                if key in seen:
                    raise yaml.YAMLError('Duplicate configuration key')
                seen.add(key)
            except TypeError:
                raise yaml.YAMLError('Invalid configuration key') from None
        return super().construct_mapping(node, deep=deep)


def load_config(path):
    try:
        config = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    except (OSError, yaml.YAMLError):
        raise GeofeedError("Cannot read YAML configuration") from None
    if not isinstance(config, dict):
        raise GeofeedError("Configuration must be a YAML mapping")
    allowed = {"source", "inputs", "credentials", "allowed_prefixes", "pool_sites", "exclude_pools", "site_locations", "publish", "state_dir", "max_removed_fraction", "max_relocated_fraction", "extensions", "bogons"}
    if set(config) - allowed:
        raise GeofeedError("Unknown configuration keys: " + ", ".join(sorted(set(config) - allowed)))
    limit = config.get("max_removed_fraction", 0.10)
    if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not 0 <= limit <= 1:
        raise GeofeedError("max_removed_fraction must be between 0 and 1")
    limit = config.get('max_relocated_fraction', 0.10)
    if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not 0 <= limit <= 1:
        raise GeofeedError('max_relocated_fraction must be between 0 and 1')
    for name in ("pool_sites", "exclude_pools", "site_locations", "publish"):
        if not isinstance(config.get(name, {}), dict):
            raise GeofeedError(f"{name} must be a YAML mapping")
    if not isinstance(config.get("allowed_prefixes", []), list):
        raise GeofeedError("allowed_prefixes must be a list")
    sources, targets = load_extensions(config.get('extensions'), SOURCES, TARGETS)
    parent = CredentialStore(config.get('credentials'))
    if 'inputs' in config:
        validate_inputs(config, sources, parent)
    else:
        validate_source(config.get('source'), sources)
    target = config.get('publish', {})
    if 'allow_initial' in target and not isinstance(target['allow_initial'], bool):
        raise GeofeedError('publish.allow_initial must be true or false')
    if target.get('type') in targets and hasattr(targets[target['type']], 'settings'):
        if set(target) - ({'type', 'allow_initial', 'location_fields'} | targets[target['type']].settings):
            raise GeofeedError('Unknown publication target configuration keys')
    return LoadedConfig(config, sources, targets)


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


def error_message(exc, credentials, stage):
    if isinstance(exc, GeofeedError):
        return credentials.redact(str(exc))
    return f"Failed while {stage} ({type(exc).__name__}); check the selected adapter's required fields and report a sanitized response shape"


@contextmanager
def publication_run(directory, credentials, stage):
    # The owner records failure before releasing the lock. A rejected contender
    # cannot overwrite the active publisher's status file.
    with run_lock(directory):
        try:
            yield
        except Exception as exc:
            try:
                status(directory, {"healthy": False, "error": error_message(exc, credentials, stage())})
            except Exception:
                print("ERROR: Could not save failure status; inspect service logs", file=sys.stderr)
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read the selected IPAM source and publish validated IP geolocation data")
    parser.add_argument("command", choices=("discover", "generate", "publish"))
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--output", help="Private discovery JSON or generated output candidate")
    parser.add_argument("--assignment-candidates", action="store_true", help="Discover observed pool use on site equipment; does not choose a host")
    parser.add_argument("--controller-candidates", action="store_true", help="Discover Sonar controller management-IP site links")
    parser.add_argument('--approve-location-changes', metavar='SHA256', help='Publish only: approve location changes for this exact reviewed candidate hash')
    args = parser.parse_args(argv)
    directory = None
    stage = "reading configuration"
    credentials = CredentialStore()
    try:
        if args.approve_location_changes is not None and (args.command != 'publish' or not re.fullmatch(r'[a-f0-9]{64}', args.approve_location_changes)):
            raise GeofeedError('--approve-location-changes requires publish and a lowercase SHA-256 candidate hash')
        config = load_config(args.config)
        credentials = CredentialStore(config.get("credentials"))
        directory = Path(config.get("state_dir", "state"))
        with publication_run(directory, credentials, lambda: stage) if args.command == "publish" else nullcontext():
            inputs = None
            if 'inputs' in config:
                stage = 'reading required input inventories'
                inputs = read_inputs(config, credentials, args.command, assignments=args.assignment_candidates, controllers=args.controller_candidates)
            else:
                source_kind = config["source"]["type"]
                adapter = config.sources[source_kind]
                stage = f"reading {source_kind} inventory"
                source = adapter.create(config["source"], credentials)
                snapshot = source.snapshot()
            if args.command == "discover":
                if inputs is not None:
                    snapshot = {'schema_version': 1, 'inputs': inputs}
                if args.assignment_candidates and inputs is None:
                    if source_kind != "sonar":
                        raise GeofeedError("--assignment-candidates applies to Sonar; NetBox reports native scopes")
                    snapshot["assignment_candidates"] = source.assignment_candidates(snapshot["sites"])
                    snapshot["candidate_warning"] = "Observed address use is not proof of pool hosting or ownership. Review before mapping."
                if args.controller_candidates and inputs is None:
                    if source_kind != "sonar":
                        raise GeofeedError("--controller-candidates applies to Sonar")
                    snapshot["controller_candidates"] = source.controller_candidates(snapshot)
                data = (json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n").encode()
                if args.output:
                    atomic_write(args.output, data)
                else:
                    print(data.decode(), end="")
                return 0
            if inputs is None:
                stage = f"selecting {source_kind} records"
                snapshot = source.for_publication(snapshot)
                if args.command == "publish" and adapter.initial and config["source"].get("allow_initial") is not True:
                    raise GeofeedError("Initial adapter: run discovery and candidate checks, then explicitly set source.allow_initial: true before publishing")
            settings = config.get('publish', {})
            target = config.targets.get(settings.get('type'))
            payload_format = getattr(target, 'payload_format', 'csv')
            available = getattr(target, 'location_fields', COARSE_FIELDS)
            required = getattr(target, 'required_fields', COARSE_FIELDS)
            requested = settings.get('location_fields', sorted(required or COARSE_FIELDS))
            if not isinstance(requested, list) or any(not isinstance(field, str) for field in requested) or len(requested) != len(set(requested)):
                raise GeofeedError('publish.location_fields must contain unique field names')
            fields = frozenset(requested)
            if not fields or fields - available or required - fields or (payload_format == 'csv' and fields != COARSE_FIELDS):
                raise GeofeedError('Selected output cannot accept those fields or is missing required location fields')
            stage = 'validating selected pools and required location fields'
            records, report = combine_inputs(inputs, config, fields) if inputs is not None else build_records(snapshot, config, fields)
            if payload_format == 'records' and any(not row['location'].get(field) and row['location'].get(field) != 0
                                                   for row in records for field in required):
                raise GeofeedError('Selected output needs nonempty required location values')
            stage = 'validating current fullbogon allocation data'
            policy = load_policy(config)
            policy.check([ipaddress.ip_network(row['prefix']) for row in records])
            if payload_format == 'csv':
                candidate = render_csv(records)
                payload = candidate
            else:
                from .records import encode_records
                candidate = encode_records(records)
                payload = records
            if args.command == "generate":
                if args.output:
                    atomic_write(args.output, candidate)
                else:
                    sys.stdout.write(candidate.decode())
                print(f"Validated {len(records)} prefixes; sha256={digest(candidate)}", file=sys.stderr)
                return 0
            if args.approve_location_changes and args.approve_location_changes != digest(candidate):
                raise GeofeedError('Location-change approval does not match this generated candidate; no write attempted')
            kwargs = {"max_removed_fraction": config.get("max_removed_fraction", 0.10),
                      'max_relocated_fraction': 1.0 if args.approve_location_changes else config.get('max_relocated_fraction', 0.10)}
            target_kind = settings.get("type")
            if target_kind not in config.targets:
                raise GeofeedError("Choose publish.type from: " + ", ".join(sorted(config.targets)))
            target = config.targets[target_kind]
            if getattr(target, 'initial', False) and settings.get('allow_initial') is not True:
                raise GeofeedError('Initial output adapter: explicitly set publish.allow_initial: true after testing')
            stage = f"publishing to {target_kind}"
            result = target(settings, credentials).publish(payload, directory, **kwargs)
            input_status = {'inputs': {name: {k: v for k, v in item.items() if k != 'snapshot'} for name, item in inputs.items()}} if inputs is not None else {}
            approval_status = {'location_change_approval_sha256': args.approve_location_changes} if args.approve_location_changes else {}
            status(directory, {"healthy": True, **result, "pools": report, **input_status, **approval_status})
            print(json.dumps(result))
        return 0
    except Exception as exc:
        # Configuration errors must never dump secrets or complete API responses.
        message = error_message(exc, credentials, stage)
        print("ERROR: " + message, file=sys.stderr)
        return 1
