"""Exact IP range conversion and conservative, explicit location selection."""
import csv
import hashlib
import io
import ipaddress
import re
from .client import GeofeedError
from .locations import COARSE_FIELDS, project_site
from .iso_codes import valid_country, valid_region
from .overlap import REJECT, LONGEST_PREFIX, validate_policy, validate_networks
from ._effective import MAX_RECORDS


def digest(data):
    return hashlib.sha256(data).hexdigest()


def prefixes(value):
    try:
        if "-" in value:
            start, end = (ipaddress.ip_address(s.strip()) for s in value.split("-", 1))
            return list(ipaddress.summarize_address_range(start, end))
        return [ipaddress.ip_network(value, strict=True)]
    except (ValueError, TypeError):
        raise GeofeedError("Pool has an invalid IP range or noncanonical prefix") from None


def public(network):
    # is_global alone includes IPv4 multicast; reject it explicitly.
    return all(a.is_global and not a.is_multicast and not a.is_unspecified
               for a in (network.network_address, network.broadcast_address)) and not any(
        network.overlaps(n) for n in SPECIAL if n.version == network.version)


SPECIAL = [ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
    "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24", "192.168.0.0/16", "198.18.0.0/15",
    "192.88.99.0/24", "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4",
    "::/96", "::ffff:0:0/96", "64:ff9b::/96", "64:ff9b:1::/48", "100::/64",
    "2001::/32", "2001:2::/48", "2001:10::/28", "2001:20::/28",
    "2001:db8::/32", "2002::/16", "3fff::/20", "5f00::/16", "fc00::/7", "fe80::/10", "fec0::/10", "ff00::/8")]


def location(site, override=None):
    override = override or {}
    addresses = site.get("addresses", [])
    if not isinstance(override, dict) or not isinstance(addresses, list) or any(not isinstance(a, dict) for a in addresses):
        raise GeofeedError(f"Site {site['id']} has invalid addresses or location override; expected structured location fields")
    address_id = override.get("address_id")
    if address_id is not None:
        addresses = [a for a in addresses if str(a.get("id")) == str(address_id)]
    if len(addresses) != 1:
        raise GeofeedError(f"Site {site['id']} needs exactly one address, or an explicit address_id")
    address = addresses[0]
    country = str(override.get("country", address.get("country")) or "").strip()
    region = str(override.get("region", address.get("subdivision")) or "").strip().replace("_", "-")
    city = str(override.get("city", address.get("city")) or "").strip()
    if not re.fullmatch(r"[A-Z]{2}", country) or not valid_country(country):
        raise GeofeedError(f"Site {site['id']} has invalid/missing country")
    if region and (not re.fullmatch(r"[A-Z]{2}-[A-Z0-9]{1,3}", region) or not region.startswith(country + "-") or not valid_region(region)):
        raise GeofeedError(f"Site {site['id']} has invalid subdivision")
    # RFC 8805 does not support quoted CSV fields; commas must be rejected.
    if not city or any(c in city for c in ',"#\r\n') or any(ord(c) < 32 or ord(c) == 127 for c in city):
        raise GeofeedError(f"Site {site['id']} has invalid/missing city")
    return country, region, city, ""  # Do not publish postal codes or street addresses.


def build_records(snapshot, config, fields=COARSE_FIELDS):
    overlap_policy = validate_policy(config.get('overlap_policy', REJECT))
    if not isinstance(snapshot, dict):
        raise GeofeedError("Source returned an invalid snapshot; expected pools and sites")
    for kind in ("pools", "sites"):
        rows = snapshot.get(kind)
        if not isinstance(rows, list):
            raise GeofeedError(f"Source returned invalid {kind}; expected a record list")
        seen = set()
        for row in rows:
            key = str(row.get("id", "")) if isinstance(row, dict) else ""
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", key):
                raise GeofeedError(f"Source {kind} contains a missing or invalid record ID")
            if key in seen:
                raise GeofeedError(f"Source {kind} contains duplicate ID {key}")
            seen.add(key)
    mappings = {str(k): str(v) for k, v in config.get("pool_sites", {}).items()}
    ignored = {str(k): v for k, v in config.get("exclude_pools", {}).items()}
    overrides = {str(k): v for k, v in config.get("site_locations", {}).items()}
    if set(mappings) & set(ignored):
        raise GeofeedError("A pool cannot be mapped and excluded")
    if any(not isinstance(v, str) or not v.strip() for v in ignored.values()):
        raise GeofeedError("Each excluded pool needs a reason")
    owned = [ipaddress.ip_network(s, strict=True) for s in config.get("allowed_prefixes", [])]
    if not owned:
        raise GeofeedError("Configure allowed_prefixes for address space you may publish")
    sites = {str(s["id"]): s for s in snapshot["sites"]}
    pools = {str(p["id"]): p for p in snapshot["pools"]}
    missing = (set(mappings) | set(ignored)) - set(pools)
    if missing:
        raise GeofeedError("Configured pools no longer exist: " + ", ".join(sorted(missing)))
    entries, report = [], []
    for pid, pool in pools.items():
        if not isinstance(pool.get("ip_range"), str):
            raise GeofeedError(f"Pool {pid} needs a string ip_range")
        try:
            nets = prefixes(pool["ip_range"])
        except GeofeedError:
            raise GeofeedError(f"Pool {pid} has an invalid IP range or noncanonical prefix") from None
        if not all(public(n) for n in nets):
            if overlap_policy == LONGEST_PREFIX and pid not in ignored:
                raise GeofeedError(f'Pool {pid} contains nonpublic or special address space; nested selection stopped')
            if any(public(n) for n in nets):
                raise GeofeedError(f"Pool {pid} crosses public and special address space")
            report.append({"pool_id": pid, "result": "nonpublic"})
            continue
        if pid in ignored:
            report.append({"pool_id": pid, "result": "excluded", "reason": ignored[pid]})
            continue
        sid = mappings.get(pid, pool.get("site_id"))
        if not sid:
            detail = pool.get("scope_error") or "No source site scope"
            raise GeofeedError(f"Public pool {pid} has no pool_sites mapping or source site scope/exclusion reason: {detail}")
        sid = str(sid)
        if sid not in sites:
            raise GeofeedError(f"Pool {pid} refers to missing network site {sid}")
        parent = pool.get("subnet")
        if not parent:
            raise GeofeedError(f"Pool {pid} has no parent subnet")
        try:
            parent_net = ipaddress.ip_network(parent["subnet"], strict=True)
        except (KeyError, ValueError, TypeError):
            raise GeofeedError(f"Pool {pid} has an invalid parent subnet") from None
        loc = project_site(sites[sid], overrides.get(sid), fields)
        for net in nets:
            if net.version != parent_net.version or not net.subnet_of(parent_net):
                raise GeofeedError(f"Pool {pid} extends outside its parent subnet")
            if not any(net.version == n.version and net.subnet_of(n) for n in owned):
                raise GeofeedError(f"Pool {pid} is outside allowed_prefixes")
            if overlap_policy == LONGEST_PREFIX and len(entries) >= MAX_RECORDS:
                raise GeofeedError('Nested-prefix policy exceeds record limit')
            entries.append((net, loc, pid))
        report.append({"pool_id": pid, "site_id": sid, "result": "mapped", "prefixes": len(nets),
                       "cidrs": [str(net) for net in nets],
                       "mapping_source": "configuration" if pid in mappings else "native_scope"})
    if not entries:
        raise GeofeedError("No public mapped prefixes; refusing an empty feed")
    entries.sort(key=lambda e: (e[0].version, int(e[0].network_address), e[0].prefixlen))
    previous, seen = None, set()
    for net, loc, pid in entries:
        if net in seen or (overlap_policy == REJECT and previous is not None
                           and previous.version == net.version and previous.overlaps(net)):
            raise GeofeedError(f'Overlapping/duplicate pool ranges near pool {pid}')
        seen.add(net)
        previous = net
    try:
        validate_networks([entry[0] for entry in entries], overlap_policy)
    except GeofeedError as exc:
        raise GeofeedError(f'Overlapping/duplicate pool ranges or unsupported record count: {exc}') from None
    return [{'prefix': str(net), 'location': loc} for net, loc, _ in entries], report


def render_csv(records, *, overlap_policy=REJECT):
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n", quoting=csv.QUOTE_NONE)
    for row in records:
        value = row['location']
        loc = location({'id': 'output', 'addresses': [{'country': value.get('country'), 'subdivision': value.get('region'), 'city': value.get('city')}]})
        writer.writerow((row['prefix'], *loc))
    value = out.getvalue().encode('utf-8')
    if overlap_policy == LONGEST_PREFIX:
        from .envelope import wrap_csv
        value = wrap_csv(value)
    parse_feed(value, overlap_policy=overlap_policy)
    return value


def build(snapshot, config):
    records, report = build_records(snapshot, config)
    return render_csv(records, overlap_policy=config.get('overlap_policy', REJECT)), report


def parse_feed(data, *, overlap_policy=REJECT):
    validate_policy(overlap_policy)
    try:
        if not data or len(data) > 1_000_000:
            raise ValueError()
        from .envelope import csv_body
        data = csv_body(data, overlap_policy)
        nets, rows = [], []
        for row in csv.reader(io.StringIO(data.decode("utf-8")), strict=True):
            if len(row) != 5 or row[4] != "":
                raise ValueError()
            net = ipaddress.ip_network(row[0], strict=True)
            if not public(net) or str(net) != row[0]:
                raise ValueError()
            location({"id": "feed", "addresses": [{"country": row[1], "subdivision": row[2], "city": row[3]}]})
            nets.append(net)
            rows.append(row)
        if not nets:
            raise ValueError()
        nets.sort(key=lambda n: (n.version, int(n.network_address), n.prefixlen))
        validate_networks(nets, overlap_policy)
        canonical = "".join(",".join(row) + "\n" for row in rows).encode()
        # Accept legacy LF snapshots for guarded migration/recovery, or uniform CRLF.
        # Never normalize stored bytes: hashes and recovery must compare exact content.
        if data not in (canonical, canonical.replace(b'\n', b'\r\n')):
            raise ValueError()
        return nets
    except (ValueError, UnicodeError, csv.Error, GeofeedError):
        raise GeofeedError("Invalid or unsafe geofeed CSV") from None


def csv_records(data, *, overlap_policy=REJECT):
    """Read validated CSV locations without losing their prefix associations."""
    rows = []
    from .envelope import csv_body
    data = csv_body(data, overlap_policy)
    for row in csv.reader(io.StringIO(data.decode('utf-8'))):
        country, region, city, _ = location({'id': 'comparison', 'addresses': [
            {'country': row[1], 'subdivision': row[2], 'city': row[3]}]})
        rows.append({'prefix': row[0], 'location': {'country': country, 'region': region, 'city': city}})
    return rows


def change_guard(old, new, max_removed_fraction=0.10, *, max_relocated_fraction=0.10, overlap_policy=REJECT, old_overlap_policy=None):
    from .relocation import relocation_guard
    new_nets = parse_feed(new, overlap_policy=overlap_policy)
    old_policy = overlap_policy if old_overlap_policy is None else validate_policy(old_overlap_policy)
    old_nets = parse_feed(old, overlap_policy=old_policy) if old else []
    if LONGEST_PREFIX in (overlap_policy, old_policy):
        from .relocation import effective_change_guard
        return effective_change_guard(csv_records(old, overlap_policy=old_policy) if old else [], csv_records(new, overlap_policy=overlap_policy),
                                      max_removed_fraction, max_relocated_fraction)
    coverage_guard(old_nets, new_nets, max_removed_fraction)
    relocation_guard(csv_records(old) if old else [], csv_records(new), max_relocated_fraction)


def coverage_guard(old_nets, new_nets, max_removed_fraction=0.10):
    from .relocation import fraction_limit
    limit = fraction_limit(max_removed_fraction, 'max_removed_fraction')
    # Measure lost address coverage by family, not row count: CIDR row counts vary.
    for version in (4, 6):
        before = [n for n in old_nets if n.version == version]
        after = [n for n in new_nets if n.version == version]
        total = sum(n.num_addresses for n in before)
        retained, i, j = 0, 0, 0
        while i < len(before) and j < len(after):
            a, b = before[i], after[j]
            left = max(int(a.network_address), int(b.network_address))
            right = min(int(a.broadcast_address), int(b.broadcast_address))
            retained += max(0, right - left + 1)
            if int(a.broadcast_address) < int(b.broadcast_address):
                i += 1
            else:
                j += 1
        if total and (total - retained) * limit.denominator > total * limit.numerator:
            raise GeofeedError(f"IPv{version} feed removal exceeds configured change limit")
