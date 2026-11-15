"""Small, bounded GraphQL reader; no mutation API and no automatic retries."""
import json
import ipaddress
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class GeofeedError(Exception):
    """An actionable failure; the last published feed must be retained."""


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def https_url(url):
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.username
            or parts.password or parts.query or parts.fragment):
        raise GeofeedError("Use an HTTPS URL without credentials, query or fragment")
    return url.rstrip("/")


class JsonHTTP:
    def __init__(self, timeout=30, max_bytes=8_000_000):
        self.timeout, self.max_bytes = timeout, max_bytes
        self.opener = build_opener(NoRedirects())

    def request(self, url, *, body=None, headers=None, method=None):
        req = Request(url, data=None if body is None else json.dumps(body).encode(),
                      headers={"User-Agent": "isp-geofeed-generator/0.1", "Content-Type": "application/json", **(headers or {})},
                      method=method)
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                content = response.read(self.max_bytes + 1)
                if len(content) > self.max_bytes:
                    raise GeofeedError("Response exceeds size limit")
                return json.loads(content)
        except HTTPError as exc:
            # Never echo request headers or upstream bodies, which may hold secrets.
            exc.close()
            raise GeofeedError(f"HTTP {exc.code}; no retry was made") from None
        except (URLError, TimeoutError, OSError) as exc:
            raise GeofeedError(f"Connection failed ({type(exc).__name__}); no retry was made") from None
        except (ValueError, UnicodeError):
            raise GeofeedError("Response is not valid JSON") from None


class Sonar:
    def __init__(self, url, token, http=None, page_size=100, settings=None):
        if not token or any(c.isspace() for c in token):
            raise GeofeedError("SONAR_API_TOKEN is missing or contains whitespace")
        base = https_url(url)
        self.url = base if base.endswith("/api/graphql") else base + "/api/graphql"
        self.headers = {"Authorization": "Bearer " + token}
        self.http = http or JsonHTTP()
        self.page_size = page_size
        self.settings = settings or {}

    def query(self, query, variables=None):
        result = self.http.request(self.url, body={"query": query, "variables": variables or {}}, headers=self.headers)
        if not isinstance(result, dict) or result.get("errors") or not isinstance(result.get("data"), dict):
            raise GeofeedError("Sonar returned GraphQL errors or no data; no partial result accepted")
        return result["data"]

    def pages(self, root, fields, *, filters="", arguments="", variables=None):
        entities, ids, total = [], set(), None
        for page in range(1, 10001):
            q = (f"query Read($page: Int!, $size: Int!{arguments}) {{ {root}("
                 f"paginator: {{page: $page, records_per_page: $size}}{filters}) {{ "
                 f"page_info {{page total_pages total_count}} entities {{ {fields} }} }} }}")
            data = self.query(q, {**(variables or {}), "page": page, "size": self.page_size}).get(root)
            try:
                info, rows = data["page_info"], data["entities"]
                count, pages = int(info["total_count"]), int(info["total_pages"])
                if int(info["page"]) != page or count < 0 or pages < 0 or not isinstance(rows, list):
                    raise ValueError()
                if total is None:
                    total = count
                if count != total:
                    raise GeofeedError("Sonar inventory changed during pagination; run again after review")
                for row in rows:
                    key = str(row["id"])
                    if key in ids:
                        raise GeofeedError("Duplicate entity while paging Sonar; inventory is incomplete")
                    ids.add(key)
                    entities.append(row)
                if page >= pages:
                    if len(entities) != total:
                        raise GeofeedError("Sonar page count does not match returned entity count")
                    return entities
                if not rows:
                    raise GeofeedError("Sonar returned an empty intermediate page")
            except (KeyError, TypeError, ValueError):
                raise GeofeedError("Sonar pagination metadata is missing or invalid") from None
        raise GeofeedError("Pagination limit exceeded")

    def snapshot(self):
        pools = self.pages("ip_pools", "id name ip_range subnet_id subnet { id subnet }")
        if not pools:
            raise GeofeedError("Sonar returned zero IP pools; not measured, publication stopped")
        sites = self.pages("network_sites", """id name addresses(paginator: {page: 1, records_per_page: 100}) {
            page_info {total_count} entities {id city country subdivision}}""")
        for site in sites:
            conn = site["addresses"]
            if len(conn["entities"]) == int(conn["page_info"]["total_count"]):
                site["addresses"] = conn["entities"]
            else:
                site["addresses"] = self.pages("addresses", "id city country subdivision",
                    arguments=", $site: Int64Bit!", filters=", addressable_type: NetworkSite, addressable_id: $site",
                    variables={"site": str(site["id"])})
        snapshot = {"pools": pools, "sites": sites}
        if self.settings.get("site_resolution") == "controllers":
            evidence = self.controller_candidates(snapshot)
            snapshot["controller_candidates"] = evidence
            for pool in pools:
                candidate = evidence[str(pool["id"])]
                if candidate["site_id"]:
                    pool["site_id"] = candidate["site_id"]
                else:
                    pool["scope_error"] = candidate["reason"]
        return snapshot

    def _related_pages(self, root, entity_id, relation, fields):
        rows, seen, total = [], set(), None
        for page in range(1, 10001):
            q = f'''query Related($id: Int64Bit!, $page: Int!, $size: Int!) {{
                {root}(id: $id) {{ entities {{ id {relation}(paginator: {{page: $page, records_per_page: $size}}) {{
                    page_info {{page total_pages total_count}} entities {{ {fields} }} }} }} }} }}'''
            parent = self.query(q, {"id": str(entity_id), "page": page, "size": self.page_size})[root]["entities"]
            if len(parent) != 1 or str(parent[0]["id"]) != str(entity_id):
                raise GeofeedError("Sonar controller changed during discovery")
            conn = parent[0][relation]
            info, batch = conn["page_info"], conn["entities"]
            count = int(info["total_count"])
            if total is None:
                total = count
            if count != total or int(info["page"]) != page:
                raise GeofeedError("Sonar controller relation changed during pagination")
            for row in batch:
                key = str(row["id"])
                if key in seen:
                    raise GeofeedError("Duplicate Sonar controller relation record")
                seen.add(key); rows.append(row)
            if page >= int(info["total_pages"]):
                if len(rows) != total:
                    raise GeofeedError("Incomplete Sonar controller relation")
                return rows
            if not batch:
                raise GeofeedError("Empty Sonar controller relation page")
        raise GeofeedError("Sonar controller relation page limit exceeded")

    def controller_candidates(self, snapshot):
        """Resolve controller IPs through inventory. Never infer a site from a name."""
        owner_fields = '''inventoryitemable_type inventoryitemable_id inventoryitemable {
            __typename ... on Address {id addressable_type addressable_id}}'''
        assignment_fields = '''id subnet ipassignmentable { __typename ... on NetworkSite {id}
            ... on InventoryItem {id ''' + owner_fields + '''}
            ... on InventoryModelFieldData {id inventory_item {id ''' + owner_fields + '''}}}'''
        result = {str(p["id"]): {"site_id": None, "reason": "No dedicated controller link", "controllers": []}
                  for p in snapshot["pools"]}
        subnets = {}
        for pool in snapshot["pools"]:
            subnets.setdefault(str(pool["subnet_id"]), []).append(str(pool["id"]))
        ip_sites = {}
        site_ids = {str(s["id"]) for s in snapshot["sites"]}

        def sites_for_ip(ip):
            ip = str(ipaddress.ip_address(ip))
            if ip in ip_sites:
                return ip_sites[ip]
            assignments = self.pages("ip_assignments", assignment_fields, arguments=", $ip: SubnetScalar!",
                filters=", subnet: $ip", variables={"ip": ip})
            matches = set()
            for assignment in assignments:
                net = ipaddress.ip_network(assignment["subnet"], strict=True)
                if net.num_addresses != 1 or str(net.network_address) != ip:
                    continue
                owner = assignment.get("ipassignmentable") or {}
                if owner.get("__typename") == "NetworkSite":
                    matches.add(str(owner["id"]))
                    continue
                if owner.get("__typename") == "InventoryModelFieldData":
                    owner = owner.get("inventory_item") or {}
                if owner.get("inventoryitemable_type") == "NetworkSite":
                    matches.add(str(owner["inventoryitemable_id"]))
                elif owner.get("inventoryitemable_type") == "Address":
                    address = owner.get("inventoryitemable") or {}
                    if address.get("addressable_type") == "NetworkSite":
                        matches.add(str(address["addressable_id"]))
            if matches - site_ids:
                raise GeofeedError("Controller references a missing site")
            ip_sites[ip] = sorted(matches)
            return ip_sites[ip]

        for root, relation, flag, kind in (("dhcp_servers", "ip_pools", "serves_all_pools", "dhcp"),
                                            ("inline_devices", "subnets", "all_subnets", "inline")):
            fields = f'''id name ip_address enabled {flag} {relation}(paginator: {{page: 1, records_per_page: 100}}) {{
                page_info {{total_count}} entities {{id}} }}'''
            for controller in self.pages(root, fields):
                if not controller["enabled"] or controller[flag]:
                    continue
                conn = controller[relation]
                linked = conn["entities"] if len(conn["entities"]) == int(conn["page_info"]["total_count"]) else self._related_pages(root, controller["id"], relation, "id")
                pool_ids = [str(row["id"]) for row in linked] if kind == "dhcp" else [pid for row in linked for pid in subnets.get(str(row["id"]), [])]
                if not pool_ids:
                    continue
                sites = sites_for_ip(controller["ip_address"])
                evidence = {"kind": kind, "controller_id": str(controller["id"]), "site_ids": sites}
                for pid in set(pool_ids):
                    if pid not in result:
                        raise GeofeedError("Sonar pool inventory changed during controller discovery")
                    result[pid]["controllers"].append(evidence)
        for candidate in result.values():
            controllers = candidate["controllers"]
            sites = {sid for row in controllers for sid in row["site_ids"]}
            if controllers and all(len(row["site_ids"]) == 1 for row in controllers) and len(sites) == 1:
                candidate.update(site_id=next(iter(sites)), reason=None)
            elif controllers:
                candidate["reason"] = "Controller management-IP site assignment is missing or conflicting"
        return result

    def assignment_candidates(self, sites):
        """Observed use, not pool ownership. Only read facility inventory."""
        result = {}
        assignment = """ip_assignments(paginator: {page: 1, records_per_page: 100}) {
            page_info {total_count} entities {id ip_pool_id}}"""
        observed = self.pages("network_sites", "id " + assignment + """
            inventory_items(paginator: {page: 1, records_per_page: 100}) {
                page_info {total_count} entities {id """ + assignment + """
                    inventory_model_field_data(paginator: {page: 1, records_per_page: 100}) {
                        page_info {total_count} entities {id """ + assignment + """}}}}""")

        def complete(conn, fallback):
            if len(conn["entities"]) == int(conn["page_info"]["total_count"]):
                return conn["entities"]
            return fallback()

        if {str(s["id"]) for s in observed} != {str(s["id"]) for s in sites}:
            raise GeofeedError("Network sites changed during discovery")
        for site in observed:
            sid = str(site["id"])
            direct = complete(site["ip_assignments"], lambda: self.pages("ip_assignments", "id ip_pool_id",
                arguments=", $site: Int64Bit!", filters=", ipassignmentable_type: NetworkSite, ipassignmentable_id: $site",
                variables={"site": sid}))
            items = complete(site["inventory_items"], lambda: self.pages("inventory_items", "id " + assignment + """
                inventory_model_field_data(paginator: {page: 1, records_per_page: 100}) {
                    page_info {total_count} entities {id """ + assignment + """}}""",
                arguments=", $site: Int64Bit!", filters=", inventoryitemable_type: NetworkSite, inventoryitemable_id: $site",
                variables={"site": sid}))
            assignments = list(direct)
            for item in items:
                iid = str(item["id"])
                assignments += complete(item["ip_assignments"], lambda: self.pages("ip_assignments", "id ip_pool_id",
                    arguments=", $item: Int64Bit!", filters=", ipassignmentable_type: InventoryItem, ipassignmentable_id: $item",
                    variables={"item": iid}))
                fields = complete(item["inventory_model_field_data"], lambda: self.pages("inventory_model_field_data", "id " + assignment,
                    arguments=", $item: Int64Bit!", filters=", inventory_item_id: $item", variables={"item": iid}))
                for field in fields:
                    assignments += complete(field["ip_assignments"], lambda: self.pages("ip_assignments", "id ip_pool_id",
                        arguments=", $field: Int64Bit!", filters=", ipassignmentable_type: InventoryModelFieldData, ipassignmentable_id: $field",
                        variables={"field": str(field["id"])}))
            for assignment in assignments:
                if assignment["ip_pool_id"] is not None:
                    pid = str(assignment["ip_pool_id"])
                    result.setdefault(pid, set()).add(sid)
        return {pid: sorted(sids) for pid, sids in result.items()}
