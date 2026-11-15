"""Exact IP range conversion and conservative, explicit location selection."""
import csv
import hashlib
import io
import ipaddress
import re
from .client import GeofeedError


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
    "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4",
    "::/96", "::ffff:0:0/96", "64:ff9b::/96", "64:ff9b:1::/48", "100::/64",
    "2001:db8::/32", "2002::/16", "3fff::/20", "fc00::/7", "fe80::/10", "ff00::/8")]


def location(site, override=None):
    override = override or {}
    addresses = site.get("addresses", [])
    address_id = override.get("address_id")
    if address_id is not None:
        addresses = [a for a in addresses if str(a["id"]) == str(address_id)]
    if len(addresses) != 1:
        raise GeofeedError(f"Site {site['id']} needs exactly one address, or an explicit address_id")
    address = addresses[0]
    country = str(override.get("country", address.get("country")) or "").strip()
    region = str(override.get("region", address.get("subdivision")) or "").strip().replace("_", "-")
    city = str(override.get("city", address.get("city")) or "").strip()
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise GeofeedError(f"Site {site['id']} has invalid/missing country")
    if region and (not re.fullmatch(r"[A-Z]{2}-[A-Z0-9]{1,3}", region) or not region.startswith(country + "-")):
        raise GeofeedError(f"Site {site['id']} has invalid subdivision")
    # RFC 8805 does not support quoted CSV fields; commas must be rejected.
    if not city or any(c in city for c in ',"#\r\n') or any(ord(c) < 32 or ord(c) == 127 for c in city):
        raise GeofeedError(f"Site {site['id']} has invalid/missing city")
    return country, region, city, ""  # Do not publish postal codes or street addresses.


def build(snapshot, config):
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
        nets = prefixes(pool["ip_range"])
        if not all(public(n) for n in nets):
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
        parent_net = ipaddress.ip_network(parent["subnet"], strict=True)
        loc = location(sites[sid], overrides.get(sid))
        for net in nets:
            if net.version != parent_net.version or not net.subnet_of(parent_net):
                raise GeofeedError(f"Pool {pid} extends outside its parent subnet")
            if not any(net.version == n.version and net.subnet_of(n) for n in owned):
                raise GeofeedError(f"Pool {pid} is outside allowed_prefixes")
            entries.append((net, loc, pid))
        report.append({"pool_id": pid, "site_id": sid, "result": "mapped", "prefixes": len(nets),
                       "mapping_source": "configuration" if pid in mappings else "native_scope"})
    if not entries:
        raise GeofeedError("No public mapped prefixes; refusing an empty feed")
    entries.sort(key=lambda e: (e[0].version, int(e[0].network_address), e[0].prefixlen))
    previous = None
    for net, loc, pid in entries:
        if previous and previous.version == net.version and int(net.network_address) <= int(previous.broadcast_address):
            raise GeofeedError(f"Overlapping/duplicate pool ranges near pool {pid}")
        previous = net
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n", quoting=csv.QUOTE_NONE)
    for net, loc, _ in entries:
        writer.writerow((str(net), *loc))
    return out.getvalue().encode("utf-8"), report


def parse_feed(data):
    try:
        if not data or len(data) > 1_000_000:
            raise ValueError()
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
        for a, b in zip(nets, nets[1:]):
            if a.version == b.version and a.overlaps(b):
                raise ValueError()
        canonical = "".join(",".join(row) + "\n" for row in rows).encode()
        if canonical != data:
            raise ValueError()
        return nets
    except (ValueError, UnicodeError, csv.Error):
        raise GeofeedError("Invalid or unsafe geofeed CSV") from None


def change_guard(old, new, max_removed_fraction=0.10):
    new_nets = parse_feed(new)
    if not old:
        return
    old_nets = parse_feed(old)
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
        if total and (total - retained) / total > max_removed_fraction:
            raise GeofeedError(f"IPv{version} feed removal exceeds configured change limit")
