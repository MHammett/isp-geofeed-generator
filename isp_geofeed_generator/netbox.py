"""Read-only NetBox IPAM source; no dependency on a billing platform."""
import ipaddress
import re
from urllib.parse import urlencode, urlsplit
from .client import GeofeedError, JsonHTTP, https_url


def enum_value(value):
    return value.get("value") if isinstance(value, dict) else value


def ref_id(value):
    if isinstance(value, dict) and value.get("id") is not None:
        return str(value["id"])
    return None


def record_id(row):
    value = str(row.get("id", "")) if isinstance(row, dict) else ""
    return value if re.fullmatch(r"[0-9]{1,20}", value) else "(unknown ID)"


class NetBox:
    def __init__(self, url, token, settings=None, http=None):
        self.settings = settings or {}
        parts = urlsplit(url)
        if self.settings.get("allow_http") is True and parts.scheme == "http":
            if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
                raise GeofeedError("Invalid NetBox URL")
            base = url.rstrip("/")
        else:
            base = https_url(url)
        self.base = base if base.endswith("/api") else base + "/api"
        if not token or any(c.isspace() for c in token):
            raise GeofeedError("NETBOX_API_TOKEN is missing or contains whitespace")
        scheme = self.settings.get("auth_scheme", "Bearer")
        if scheme not in ("Bearer", "Token"):
            raise GeofeedError("NetBox auth_scheme must be Bearer or Token")
        self.headers = {"Authorization": scheme + " " + token, "Accept": "application/json"}
        self.http = http or JsonHTTP()

    def pages(self, path):
        rows, seen, total, offset = [], set(), None, 0
        url = self.base + path
        for _ in range(10000):
            data = self.http.request(url + "?" + urlencode({"limit": 100, "offset": offset}),
                                     headers=self.headers, method="GET")
            try:
                count, batch, following = data["count"], data["results"], data["next"]
                if isinstance(count, bool) or not isinstance(count, int) or count < 0 or not isinstance(batch, list):
                    raise ValueError()
                if total is None:
                    total = count
                if total != count:
                    raise GeofeedError("NetBox inventory changed during pagination")
                for row in batch:
                    if not isinstance(row, dict) or record_id(row) == "(unknown ID)":
                        raise GeofeedError(f"NetBox {path} returned a malformed record at offset {offset}")
                    key = str(row["id"])
                    if key in seen:
                        raise GeofeedError("Duplicate NetBox record during pagination")
                    seen.add(key)
                    rows.append(row)
                if not following:
                    if len(rows) != total:
                        raise GeofeedError("NetBox result count is incomplete")
                    return rows
                next_parts, expected = urlsplit(following), urlsplit(url)
                if (next_parts.scheme not in {expected.scheme, "http"} or
                    (next_parts.netloc, next_parts.path) != (expected.netloc, expected.path) or
                    next_parts.username or next_parts.password or next_parts.fragment):
                    raise GeofeedError("NetBox next-page URL is outside the requested endpoint")
                if not batch or len(rows) >= total:
                    raise GeofeedError("Invalid NetBox pagination continuation")
                # Use our own offset. Never forward credentials to an API-supplied URL.
                offset += len(batch)
            except (KeyError, TypeError, ValueError):
                raise GeofeedError(f"NetBox {path} pagination response is invalid at offset {offset}") from None
        raise GeofeedError("NetBox pagination limit exceeded")

    def _scope_site(self, prefix, locations):
        scope_type, scope_id = prefix.get("scope_type"), prefix.get("scope_id")
        if scope_type == "dcim.site" and scope_id is not None:
            return str(scope_id), None
        if scope_type == "dcim.location" and scope_id is not None:
            site = ref_id(locations.get(str(scope_id), {}).get("site"))
            return site, None if site else "Location has no resolvable site"
        if scope_type:
            return None, f"Scope {scope_type} does not identify one site"
        # NetBox before 4.2 used a direct site field.
        site = ref_id(prefix.get("site"))
        return site, None if site else "Prefix has no site scope"

    def _selected(self, kind, row):
        settings = self.settings
        tag = settings.get("tag")
        ids = settings.get(kind + "_ids", [])
        chosen = (any(t.get("slug") == tag for t in row.get("tags", [])) if tag else
                  str(row["id"]) in {str(i) for i in ids})
        statuses = settings.get("statuses", ["active"])
        vrfs = {str(v) for v in settings.get("vrf_ids", ["global"])}
        vrf = ref_id(row.get("vrf")) or "global"
        return bool(chosen and enum_value(row.get("status")) in statuses and vrf in vrfs)

    def snapshot(self):
        prefixes = self.pages("/ipam/prefixes/")
        ranges = self.pages("/ipam/ip-ranges/")
        if not prefixes and not ranges:
            raise GeofeedError("NetBox returned zero prefixes and ranges; not measured")
        sites = self.pages("/dcim/sites/")
        locations = ({str(r["id"]): r for r in self.pages("/dcim/locations/")}
                     if any(p.get("scope_type") == "dcim.location" for p in prefixes) else {})
        fields = {"country": "geofeed_country", "region": "geofeed_region", "city": "geofeed_city",
                  **self.settings.get("location_fields", {})}
        normalized_sites = []
        for site in sites:
            custom = site.get("custom_fields") or {}
            if not isinstance(custom, dict):
                raise GeofeedError(f"NetBox site {record_id(site)} has invalid custom_fields; expected a mapping")
            if not isinstance(site.get("name"), str):
                raise GeofeedError(f"NetBox site {record_id(site)} has no valid name")
            address = {"id": "site:" + str(site["id"]),
                       "country": enum_value(custom.get(fields["country"])),
                       "subdivision": enum_value(custom.get(fields["region"])),
                       "city": enum_value(custom.get(fields["city"]))}
            normalized_sites.append({"id": str(site["id"]), "name": site["name"], "addresses": [address]})
        normalized, index = [], []
        for prefix in prefixes:
            try:
                network = ipaddress.ip_network(prefix["prefix"], strict=True)
            except (KeyError, ValueError, TypeError):
                raise GeofeedError(f"NetBox prefix {record_id(prefix)} has a missing, invalid or noncanonical prefix") from None
            index.append((prefix, network))
            sid, error = self._scope_site(prefix, locations)
            normalized.append({"id": "prefix:" + str(prefix["id"]), "name": prefix.get("description") or prefix["prefix"],
                "ip_range": str(network), "subnet": {"subnet": str(network)},
                "site_id": sid, "scope_error": error, "selected": self._selected("prefix", prefix),
                "source_status": enum_value(prefix.get("status")), "vrf_id": ref_id(prefix.get("vrf"))})
        for row in ranges:
            try:
                start = ipaddress.ip_interface(row["start_address"]).ip
                end = ipaddress.ip_interface(row["end_address"]).ip
            except (KeyError, ValueError, TypeError):
                raise GeofeedError(f"NetBox range {record_id(row)} has missing or invalid boundaries") from None
            if start.version != end.version or int(start) > int(end):
                raise GeofeedError(f"NetBox range {record_id(row)} has reversed or mixed-family boundaries")
            parents = [(p, n) for p, n in index if n.version == start.version and start in n and end in n
                       and ref_id(p.get("vrf")) == ref_id(row.get("vrf"))]
            sid, error, parent = None, "Range has no containing prefix in the same VRF", None
            if parents:
                length = max(n.prefixlen for _, n in parents)
                closest = [(p, n) for p, n in parents if n.prefixlen == length]
                if len(closest) == 1:
                    parent, network = closest[0]
                    sid, error = self._scope_site(parent, locations)
                    parent = str(network)
                else:
                    error = "Range has ambiguous equally specific parent prefixes"
            # Missing parent remains visible to discovery, but cannot be published.
            normalized.append({"id": "range:" + str(row["id"]), "name": row.get("description") or f"Range {row['id']}",
                "ip_range": f"{start}-{end}", "subnet": {"subnet": parent} if parent else None,
                "site_id": sid, "scope_error": error, "selected": self._selected("range", row),
                "source_status": enum_value(row.get("status")), "vrf_id": ref_id(row.get("vrf"))})
        return {"source": "netbox", "pools": normalized, "sites": normalized_sites}

    def for_publication(self, snapshot):
        settings = self.settings
        if not settings.get("tag") and not (settings.get("prefix_ids") or settings.get("range_ids")):
            raise GeofeedError("Select NetBox records with a tag or explicit prefix_ids/range_ids")
        pool_ids = {p["id"] for p in snapshot["pools"]}
        required = {"prefix:" + str(i) for i in settings.get("prefix_ids", [])}
        required |= {"range:" + str(i) for i in settings.get("range_ids", [])}
        if required - pool_ids:
            raise GeofeedError("Configured NetBox objects no longer exist: " + ", ".join(sorted(required - pool_ids)))
        selected = [p for p in snapshot["pools"] if p["selected"]]
        if not selected:
            raise GeofeedError("No NetBox records match publication selection, status and VRF")
        return {**snapshot, "pools": selected}
