"""Small, bounded GraphQL reader; no mutation API and no automatic retries."""
import json
import ipaddress
import re
from . import __version__
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener


class GeofeedError(Exception):
    """An actionable failure; the last published feed must be retained."""


def record_id(row):
    """Only bounded native numeric IDs are suitable for source diagnostics."""
    value = row.get('id') if isinstance(row, dict) else None
    if type(value) is int and 0 <= value < 10**20:
        return str(value)
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,20}', value):
        return value
    return '(unknown ID)'


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

    def request(self, url, *, body=None, form=None, headers=None, method=None):
        if body is not None and form is not None:
            raise GeofeedError('A request cannot contain both JSON and form data')
        payload = urlencode(form).encode() if form is not None else None if body is None else json.dumps(body).encode()
        content_type = 'application/x-www-form-urlencoded' if form is not None else 'application/json'
        req = Request(url, data=payload,
                      headers={"User-Agent": "isp-geofeed-generator/" + __version__, "Content-Type": content_type, **(headers or {})},
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
    def for_publication(self, snapshot):
        pools = snapshot['pools']
        selected = []
        for kind, ids in (('pool', self.pool_ids), ('subnet', self.subnet_ids)):
            rows = [row for row in pools if row.get('source_kind', 'pool') == kind]
            if ids is not None:
                found = {row.get('source_id', str(row['id'])) for row in rows}
                if ids - found:
                    raise GeofeedError(f'Configured Sonar {kind} IDs no longer exist or are not visible')
                rows = [row for row in rows if row.get('source_id', str(row['id'])) in ids]
            for row in rows:
                if kind == 'subnet' and row['subnet_type'] == 'EXCLUDED':
                    raise GeofeedError(f"Sonar {row['id']} is EXCLUDED; select an active service subnet")
            selected.extend(rows)
        if not selected:
            raise GeofeedError('No Sonar pools or explicitly selected subnets; publication stopped')
        return {**snapshot, 'pools': selected}

    @staticmethod
    def selected_ids(settings, key):
        if key not in settings:
            return None
        values = settings[key]
        if (not isinstance(values, list) or any(not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,19}', value) for value in values)
                or len(values) != len(set(values))):
            raise GeofeedError(f'Sonar source.{key} must contain unique positive digit-string IDs')
        return set(values)

    def __init__(self, url, token, http=None, page_size=100, settings=None):
        if not token or any(c.isspace() for c in token):
            raise GeofeedError("SONAR_API_TOKEN is missing or contains whitespace")
        base = https_url(url)
        self.url = base if base.endswith("/api/graphql") else base + "/api/graphql"
        self.headers = {"Authorization": "Bearer " + token}
        self.http = http or JsonHTTP()
        self.page_size = page_size
        self.settings = settings or {}
        self.pool_ids = self.selected_ids(self.settings, 'pool_ids')
        self.subnet_ids = self.selected_ids(self.settings, 'subnet_ids') or set()
        self.read_subnets = 'subnet_ids' in self.settings

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
                    raise GeofeedError(f'Sonar {root} inventory changed during pagination on page {page}; run again after review')
                for row in rows:
                    key = record_id(row)
                    if key == '(unknown ID)':
                        raise GeofeedError(f'Sonar {root} record (unknown ID) has a missing or invalid ID on page {page}')
                    if key in ids:
                        raise GeofeedError(f'Sonar {root} record {key} is duplicated on page {page}; inventory is incomplete')
                    ids.add(key)
                    entities.append(row)
                if page >= pages:
                    if len(entities) != total:
                        raise GeofeedError(f'Sonar {root} result count is incomplete on page {page}')
                    return entities
                if not rows:
                    raise GeofeedError(f'Sonar {root} returned an empty intermediate page {page}')
            except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
                raise GeofeedError(f'Sonar {root} pagination metadata is missing or invalid on page {page}') from None
        raise GeofeedError("Pagination limit exceeded")

    def snapshot(self):
        pools = self.pages("ip_pools", "id name ip_range subnet_id subnet { id subnet }") if self.pool_ids != set() else []
        if self.read_subnets:
            for row in self.pages('subnets', 'id name subnet type'):
                sid = str(row.get('id', ''))
                if not re.fullmatch(r'[1-9][0-9]{0,19}', sid):
                    raise GeofeedError('Sonar subnet has a missing or invalid ID')
                try:
                    network = ipaddress.ip_network(row['subnet'], strict=True)
                except (KeyError, TypeError, ValueError):
                    raise GeofeedError(f'Sonar subnet:{sid} has an invalid or noncanonical prefix') from None
                if row.get('type') not in ('ACCOUNT', 'MIXED', 'NETWORK', 'EXCLUDED'):
                    raise GeofeedError(f'Sonar subnet:{sid} has an invalid subnet type')
                pools.append({'id': 'subnet:' + sid, 'source_id': sid, 'source_kind': 'subnet',
                    'name': row.get('name'), 'subnet_type': row['type'],
                    'ip_range': str(network), 'subnet_id': sid, 'subnet': {'id': sid, 'subnet': str(network)}})
        if not pools:
            raise GeofeedError("Sonar returned zero pools/subnets for the requested inventory; not measured, publication stopped")
        sites = self.pages("network_sites", """id name addresses(paginator: {page: 1, records_per_page: 100}) {
            page_info {total_count} entities {id city country subdivision}}""")
        for site in sites:
            try:
                conn = site['addresses']
                batch, count = conn['entities'], int(conn['page_info']['total_count'])
                if not isinstance(batch, list) or count < len(batch):
                    raise ValueError()
            except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
                raise GeofeedError(f'Sonar network site {record_id(site)} has invalid addresses connection metadata') from None
            if len(batch) == count:
                site["addresses"] = batch
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

    def _related_pages(self, root, entity_id, relation, fields, *, expected_total=None):
        kind = 'DHCP server' if root == 'dhcp_servers' else 'inline device'
        label = f'Sonar {kind} {record_id({"id": entity_id})}'
        try:
            return self._controller_relation_pages(root, entity_id, relation, fields, expected_total=expected_total)
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
            raise GeofeedError(f'{label} has invalid {relation} pagination metadata') from None
        except GeofeedError as exc:
            raise GeofeedError(f'{label}: {exc}') from None

    def _controller_relation_pages(self, root, entity_id, relation, fields, *, expected_total=None):
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
            if expected_total is not None and count != expected_total:
                raise GeofeedError('Sonar controller relation count changed after inventory read')
            if total is None:
                total = count
            if count != total or int(info["page"]) != page:
                raise GeofeedError("Sonar controller relation changed during pagination")
            for row in batch:
                key = str(row["id"])
                if not re.fullmatch(r'[1-9][0-9]{0,19}', key) or key in seen:
                    raise GeofeedError("Invalid or duplicate Sonar controller relation record")
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
            if not isinstance(pool, dict) or pool.get('subnet_id') is None:
                raise GeofeedError(f'Sonar IP pool {record_id(pool)} has a missing parent subnet_id')
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
            def add_site(value, assignment):
                sid = record_id({'id': value})
                if sid == '(unknown ID)':
                    raise GeofeedError(f'Sonar IP assignment {record_id(assignment)} has an invalid network site reference')
                if sid not in site_ids:
                    raise GeofeedError(f'Sonar IP assignment {record_id(assignment)} references a missing network site')
                matches.add(sid)
            for assignment in assignments:
                try:
                    net = ipaddress.ip_network(assignment["subnet"], strict=True)
                    if net.num_addresses != 1 or str(net.network_address) != ip:
                        continue
                    owner = assignment.get("ipassignmentable") or {}
                    if owner.get("__typename") == "NetworkSite":
                        add_site(owner['id'], assignment)
                        continue
                    if owner.get("__typename") == "InventoryModelFieldData":
                        owner = owner.get("inventory_item") or {}
                    if owner.get("inventoryitemable_type") == "NetworkSite":
                        add_site(owner['inventoryitemable_id'], assignment)
                    elif owner.get("inventoryitemable_type") == "Address":
                        address = owner.get("inventoryitemable") or {}
                        if address.get("addressable_type") == "NetworkSite":
                            add_site(address['addressable_id'], assignment)
                except (KeyError, TypeError, ValueError, AttributeError):
                    raise GeofeedError(f'Sonar IP assignment {record_id(assignment)} has invalid subnet or inventory/site ownership fields') from None
            ip_sites[ip] = sorted(matches)
            return ip_sites[ip]

        for root, relation, flag, kind in (("dhcp_servers", "ip_pools", "serves_all_pools", "dhcp"),
                                            ("inline_devices", "subnets", "all_subnets", "inline")):
            if kind == 'dhcp' and not any(p.get('source_kind', 'pool') == 'pool' for p in snapshot['pools']):
                continue
            fields = f'''id name ip_address enabled {flag} {relation}(paginator: {{page: 1, records_per_page: 100}}) {{
                page_info {{total_count}} entities {{id}} }}'''
            for controller in self.pages(root, fields):
                label = f'Sonar {"DHCP server" if kind == "dhcp" else "inline device"} {record_id(controller)}'
                if record_id(controller) == '(unknown ID)':
                    raise GeofeedError(f'{label} has a missing or invalid ID')
                if type(controller.get('enabled')) is not bool or type(controller.get(flag)) is not bool:
                    raise GeofeedError(f'{label} has invalid enabled/global flags')
                if not controller["enabled"] or controller[flag]:
                    continue
                try:
                    conn = controller[relation]
                    batch, count = conn['entities'], conn['page_info']['total_count']
                    if type(count) is not int or count < 0 or not isinstance(batch, list) or len(batch) > count:
                        raise ValueError()
                    ids = [str(row['id']) for row in batch]
                    if len(ids) != len(set(ids)) or any(not re.fullmatch(r'[1-9][0-9]{0,19}', value) for value in ids):
                        raise ValueError()
                except (KeyError, TypeError, ValueError, AttributeError):
                    raise GeofeedError(f'{label} link metadata is missing, invalid or duplicated') from None
                linked = batch if len(batch) == count else self._related_pages(root, controller['id'], relation, 'id', expected_total=count)
                pool_ids = [str(row["id"]) for row in linked] if kind == "dhcp" else [pid for row in linked for pid in subnets.get(str(row["id"]), [])]
                if not pool_ids:
                    continue
                try:
                    management_ip = str(ipaddress.ip_address(controller['ip_address']))
                except (KeyError, TypeError, ValueError):
                    raise GeofeedError(f'{label} has an invalid or missing management IP') from None
                sites = sites_for_ip(management_ip)
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

        def complete(row, relation, kind, fallback):
            try:
                conn = row[relation]
                batch, count = conn['entities'], int(conn['page_info']['total_count'])
                if not isinstance(batch, list) or count < len(batch):
                    raise ValueError()
            except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
                raise GeofeedError(f'Sonar {kind} {record_id(row)} has invalid {relation} connection metadata') from None
            if len(batch) == count:
                return batch
            return fallback()

        if {str(s["id"]) for s in observed} != {str(s["id"]) for s in sites}:
            raise GeofeedError("Network sites changed during discovery")
        for site in observed:
            sid = str(site["id"])
            direct = complete(site, 'ip_assignments', 'network site', lambda: self.pages("ip_assignments", "id ip_pool_id",
                arguments=", $site: Int64Bit!", filters=", ipassignmentable_type: NetworkSite, ipassignmentable_id: $site",
                variables={"site": sid}))
            items = complete(site, 'inventory_items', 'network site', lambda: self.pages("inventory_items", "id " + assignment + """
                inventory_model_field_data(paginator: {page: 1, records_per_page: 100}) {
                    page_info {total_count} entities {id """ + assignment + """}}""",
                arguments=", $site: Int64Bit!", filters=", inventoryitemable_type: NetworkSite, inventoryitemable_id: $site",
                variables={"site": sid}))
            assignments = list(direct)
            for item in items:
                iid = record_id(item)
                if iid == '(unknown ID)':
                    raise GeofeedError(f'Sonar network site {sid} has an inventory item with a missing or invalid ID')
                assignments += complete(item, 'ip_assignments', 'inventory item', lambda: self.pages("ip_assignments", "id ip_pool_id",
                    arguments=", $item: Int64Bit!", filters=", ipassignmentable_type: InventoryItem, ipassignmentable_id: $item",
                    variables={"item": iid}))
                fields = complete(item, 'inventory_model_field_data', 'inventory item', lambda: self.pages("inventory_model_field_data", "id " + assignment,
                    arguments=", $item: Int64Bit!", filters=", inventory_item_id: $item", variables={"item": iid}))
                for field in fields:
                    fid = record_id(field)
                    if fid == '(unknown ID)':
                        raise GeofeedError(f'Sonar inventory item {iid} has field data with a missing or invalid ID')
                    assignments += complete(field, 'ip_assignments', 'inventory field', lambda: self.pages("ip_assignments", "id ip_pool_id",
                        arguments=", $field: Int64Bit!", filters=", ipassignmentable_type: InventoryModelFieldData, ipassignmentable_id: $field",
                        variables={"field": fid}))
            for assignment in assignments:
                if not isinstance(assignment, dict) or 'ip_pool_id' not in assignment:
                    raise GeofeedError(f'Sonar IP assignment {record_id(assignment)} has a missing ip_pool_id field')
                if assignment['ip_pool_id'] is not None:
                    pid = record_id({'id': assignment['ip_pool_id']})
                    if pid == '(unknown ID)':
                        raise GeofeedError(f'Sonar IP assignment {record_id(assignment)} has an invalid ip_pool_id reference')
                    result.setdefault(pid, set()).add(sid)
        return {pid: sorted(sids) for pid, sids in result.items()}
