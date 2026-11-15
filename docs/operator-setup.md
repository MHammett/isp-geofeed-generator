# Prepare your instance

The generator reads records. It does not repair billing/IPAM data or change provisioning settings.
Use your platform's normal change process for the setup below.

## Sonar

1. Create or verify the network site and its country, subdivision and city address values.
2. Assign the physical or virtual controller's inventory record to that site, or to an address belonging to that site.
3. Record the controller's exact management IP assignment on that inventory record or one of its inventory fields.
4. Link each pool to its DHCP server. For an inline device, link the pool's parent subnet to that device.
5. Use `source.site_resolution: controllers` to derive hosting sites from those records.
6. Generate discovery output and check each controller-derived site.
7. Use `pool_sites` overrides for pools whose service location differs from the controller's facility.

Sonar has a direct pool-to-DHCP-server relationship and a subnet-to-inline-device relationship.
The controller records do not expose a direct network-site field in the schema checked here.
Their management-IP inventory assignments provide the next link.

Controllers configured for all pools or all subnets are not used to infer one pool's host.
Disabled controllers are also ignored. Missing or conflicting site assignments stop automatic resolution.
Two dedicated controllers at different sites need an explicit per-pool decision.
An inventory-IP assignment can interact with provisioning; check your integration rules before adding one.
Do not create a customer DHCP reservation merely to satisfy a discovery check.

The host of a central DHCP or policy device is not necessarily the subscriber's town.
Choose the geolocation policy you want before accepting automatically derived hosting-site locations.

## NetBox

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

Create a dedicated API application with read-only access and use a supported API token.
Set `PHPIPAM_URL`, `PHPIPAM_APP_ID` and a secure `PHPIPAM_API_TOKEN` reference.
Select `source.subnet_ids`, assign each subnet's location, and configure that location's `site_locations` values.
Folder records cannot be published. Parent/child overlap is rejected.

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

Run discovery, compare its counts and associations with the platform, generate a candidate, and inspect
the location policy. Test first publication and rollback on staging. Enable a timer only after the real workload passes.
See [credential storage](security.md), [WordPress setup](wordpress.md), and the [capability matrix](platforms.md).
