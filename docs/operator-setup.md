# Prepare your instance

The generator reads records. It does not repair billing/IPAM data or change provisioning settings.
Use your platform's normal change process for the setup below.

## Sonar

Sonar uses IPv4 pools and assigns IPv6 directly from subnets through DHCP/RADIUS, as its
[IPAM setup guide](https://docs.sonar.expert/networking/ipam-policy-best-practices) explains.
The adapter reads IPv4 pools by default. Add `source.subnet_ids` to read subnet inventory
and explicitly choose IPv4 or IPv6 prefixes for publication. It never selects all subnets
or publishes an entire supernet automatically.

```yaml
source:
  type: sonar
  subnet_ids: ["201", "202"]
  site_resolution: controllers
  # pool_ids: []  # No IPv4 pool reads or publication. Omit to retain all existing pools.
  # pool_ids: ["101"]  # Or choose specific native pool IDs.
```

Use native positive digit-string IDs in the source lists. In discovery, mappings and exclusions,
subnets use `subnet:201`; existing pool IDs remain `101`. This avoids collisions when a pool
and subnet share a number. For example, `pool_sites: {"subnet:201": "11"}` provides a reviewed
site override. The generic `pool_sites` and `exclude_pools` keys apply to both kinds.

To discover available subnets without publishing any of them, set `subnet_ids: []` and run
`discover`. Then choose the intended service subnet IDs. `pool_ids: []` skips pool reads, so
an IPv6-only instance does not need pool records or pool-read permissions. Grant subnet,
network-site and address reads; controller resolution also needs inline-device, management-IP
assignment and inventory-holder reads. Keep discovery exports private.

Each selected subnet publishes its exact CIDR. EXCLUDED subnets and missing selected IDs stop
the run. An IPv4 subnet without a pool is supported the same way. Do not select an IPv4 parent
subnet along with overlapping pools, or a parent subnet and its child: shared overlap checks
will refuse the feed. Choose service aggregates that match your location policy, not every
customer delegation. There is no automatic aggregation across customer assignments.

1. Create or verify the network site and its country, subdivision and city address values.
2. Assign the physical or virtual controller's inventory record to that site, or to an address belonging to that site.
3. Record the controller's exact management IP assignment on that inventory record or one of its inventory fields.
4. Link each IPv4 pool to its DHCP server. Link each selected IPv6 subnet, or an IPv4 pool's parent subnet, to its inline device.
5. Use `source.site_resolution: controllers` to derive hosting sites from those records.
6. Generate discovery output and check each controller-derived site.
7. Use `pool_sites` overrides for pools or subnets whose service location differs from the controller's facility.

Sonar has a direct pool-to-DHCP-server relationship and a subnet-to-inline-device relationship.
The controller records do not expose a direct network-site field in the schema checked here.
Their management-IP inventory assignments provide the next link.
For selected subnets, DHCP pool links are not site evidence. Only the subnet-to-inline-device
path is used. The controller management address can be IPv4 or IPv6; it must have an exact
host assignment. A broader routed prefix does not prove the device belongs to that site.

Controllers configured for all pools or all subnets are not used to infer one pool's host.
Disabled controllers are also ignored. Missing or conflicting site assignments stop automatic resolution.
Two dedicated controllers at different sites need an explicit per-pool decision.
An inventory-IP assignment can interact with provisioning; check your integration rules before adding one.
Do not create a customer DHCP reservation merely to satisfy a discovery check.

The host of a central DHCP or policy device is not necessarily the subscriber's town.
Choose the geolocation policy you want before accepting automatically derived hosting-site locations.
If one subnet spans several facilities, use smaller service subnets or reviewed explicit mappings.
Missing inventory links are an instance setup gap; they do not mean Sonar lacks IPv6 support.

Subnet fields and controller-to-site resolution have read-only live evidence. The available
test instance had no IPv6 subnets, so positive IPv6 generation/publication is fixture-tested,
not live-verified. Compare discovery and candidates with your IPv6 inventory before scheduling.
The mandatory fullbogon, allowed-prefix and per-family withdrawal checks apply to both families.

## NetBox

Pagination uses `next` only to signal that more results exist. A proxy may rewrite that
link's hostname, scheme or path. The reader still sends every request to the configured
endpoint with its own offset; credentials are never sent to the server-supplied link.
Count mismatches, duplicate records, empty intermediate pages and malformed continuation
metadata still stop the read. Check the configured public/proxy URL before scheduling.

The adapter targets NetBox 4.x API records. Authentication defaults to `Token`, which works
on 4.0 through current 4.x, including newer token types. Explicit `auth_scheme: Bearer` needs
4.5 or later. Only 4.7.3 was live-tested; older-version compatibility was checked against
vendor source and fixtures. A 401/403 or empty inventory requires checking token permissions
and the selected header before treating it as missing data.

1. Create or verify the site's geographic values.
2. Add text custom fields on Site named `geofeed_country`, `geofeed_region` and `geofeed_city`.
3. Use an ISO country code and subdivision code, such as `US` and `US-IL`. Enter the desired city.
4. Assign each publishing prefix's Scope to a site or a location that belongs to one site.
5. Tag only the intended records `geofeed`, or select them by explicit IDs.
6. Select the correct VRF. The default is the global table and active status.

Alternatively, use private `site_locations` configuration instead of custom fields.
Custom field names can also be changed through `source.location_fields`.
Country/region/city selection custom fields may return value/label objects; the adapter uses the stored value.
NetBox's ordinary region names are not assumed to be ISO subdivision codes.
Free-form physical addresses and coordinates are not guessed or sent to a geocoding service.

An IP range takes its site from the most specific containing prefix in the same VRF.
Duplicate equally specific parents are an error. A more specific unscoped prefix does not silently inherit
a broader site's location. Scope it correctly or supply an explicit override.
Selecting both a parent prefix and a child range causes an overlap error; tag/select the intended publication units only.

These are setup requirements the platform can meet. They are not claims that NetBox lacks the capability.
These steps describe the default `site` mode. Existing prefix-field or Region-hierarchy
instances can instead use the [explicit alternate models](netbox-location-models.md).

## Splynx: initial support

Use the vendor's API v2 networking read permissions and a dedicated key/secret.
The adapter signs requests. It does not require enabling the API key's Basic “Unsecure access” mode.
Select `ipv4:<id>` or `ipv6:<id>` in `source.network_ids`.
Only endnet networks with pool/static usage may be selected.

Map each selected network to a network site through `pool_sites`.
If each administrative location has exactly one agreed hosting site, a reviewed `source.location_sites`
mapping may be used instead. The adapter never guesses that relationship from matching names.
Provide `site_locations` for the coarse country/region/city values.

The adapter pages with limit/offset and stable ID ordering. It requests another page after a short page,
and stops on an empty one. The documented array response supplies no total count; operators must check
the discovery count against their instance. Concurrent deletion during paging cannot be fully detected.

## phpIPAM: initial support

For unattended runs, create a dedicated read-only API application in **SSL with App code token**
mode. Store its app token through a secure `PHPIPAM_API_TOKEN` reference. HTTPS is required.
User tokens expire and are not renewed by this reader; a successful setup trial with a user
token does not prove a daily schedule will keep working. The adapter never logs in with a
human password, resets a token or changes the API app. Retrieve the right token from your
approved secret manager before changing credentials.
Set `PHPIPAM_URL` and either `PHPIPAM_APP_ID` or `source.app_id`. Named inputs use their own
`url`, `source.app_id` and credential references. Authentication refusals point to token expiry,
app mode and read permissions without logging response bodies.
See [phpIPAM authentication](https://phpipam.net/api-documentation/#static-authentication).
Select `source.subnet_ids`, assign each subnet's location, and configure that location's `site_locations` values.
Folder records cannot be published. Parent/child overlap is rejected.

If your instance does not use native locations, explicitly choose `source.location_mode: configured`
and declare `source.facility_ids`. For example:

```yaml
source:
  type: phpipam
  app_id: geofeed
  subnet_ids: ["101"]
  location_mode: configured
  facility_ids: [facility-1]
  allow_initial: false
pool_sites: {"subnet:101": facility-1}
site_locations:
  facility-1: {country: US, region: US-IL, city: Example City}
```

This is an explicit location policy. The reader does not query the locations endpoint or use
subnet location values in configured mode. Each selected public subnet still needs a reviewed
mapping to a declared facility and valid location values. Missing mappings, locations or subnet
reads fail closed. Native mode remains the default and native location API failures still stop
the run. The tool does not treat arbitrary 404/403 responses as an empty successful collection.
See [the configured example](../config.phpipam-configured.yaml.example).

The adapter reads the documented complete subnet and location collections. A response that is too large
fails the size check. It does not silently publish the first part of a response.

## Powercode legacy API: initial support

Set `POWERCODE_URL` to the HTTPS billing origin, including its port, or the full legacy
`/api/1/index.php` endpoint. Set a secure `POWERCODE_API_KEY` reference.
Use a dedicated key limited to the documented `readAddressRanges` action where the platform's
permissions permit. The adapter does not use the current REST API or query customer equipment.

Select raw IDs in `source.range_ids`. Define stable local facility IDs in `source.facility_ids`,
map `range:<id>` to a facility in `pool_sites`, and provide `site_locations` for that facility.
The reviewed legacy response has no facility ID. This is a limit of that export, not a claim
that Powercode cannot model Network Locations. A future verified native join can replace the manual map.

The response is documented as all ranges, without paging or a total count. Compare the discovery
count with your instance before publishing. A silent server-side truncation cannot be proven absent
from this contract alone. Exact endpoints are preserved; a derived containing envelope is used
only for validation and never expands the published range. IPv6 conversion is fixture-tested if
returned in that shape. Whether this legacy action exports your IPv6 inventory is not live-verified.

## gaiia: initial support

Use `GAIIA_URL=https://api.gaiia.com/api/v1` or the documented endpoint for your deployment.
Create a dedicated secret API key under Admin > API keys. Grant only network-site/IP-block reads.
The adapter sends `X-Gaiia-Api-Key` from secure `GAIIA_API_KEY` storage.

Assign IP blocks to the correct Network Site in gaiia. Set its country, region and locality.
Choose raw `source.site_ids` to publish all blocks at reviewed sites, or `source.block_ids`
to choose individual blocks. Do not use both. Archived sites cannot be selected. A selected
site that loses every block stops the run for review.

Discovery reports native `source_id` values and safe normalized `id` values. Selection uses native
GlobalID strings. Top-level `pool_sites` and `site_locations` overrides use normalized IDs from discovery.
The normalized suffix is the URL-safe base64 encoding of the native ID, without padding.
IDs longer than the core's normalized limit are rejected, not shortened or guessed.

The adapter reads only coarse address fields. It prefixes short region codes with the country,
for example `US` and `IL` become `US-IL`. It does not guess a country or translate a full region name.
Use a reviewed location override if the native address uses another format.
It pages the site list and each site's block list separately, verifies counts and rejects
duplicate IDs, missing pages, repeated cursors, partial GraphQL errors and changed ownership/archive state.
The API is not a transactional snapshot; edits that preserve counts may still happen during reads.
Rate-limit errors stop the run without retries. See the vendor's rate-limit guidance before scheduling large inventories.

## Verify before scheduling

For Infoblox NIOS, see [network input setup](infoblox-nios.md). Select native network
references and declare string geography attributes. Keep network views separate from
physical locations. Certificate-auth and cloud API families are not implemented here.

For BillMax, see [initial AP-network setup](billmax.md). Select reviewed IPv4 `/16` or
`/24` AP networks, keep their native POP assignments and supply ISO geography overrides
when display values need translation. General pool exports and IPv6 are not claimed.

Run discovery, compare its counts and associations with the platform, generate a candidate, and inspect
the location policy. Test first publication and rollback on staging. Enable a timer only after the real workload passes.
See [credential storage](security.md), [WordPress setup](wordpress.md), and the [capability matrix](platforms.md).
