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

## Verify before scheduling

Run discovery, compare its counts and associations with the platform, generate a candidate, and inspect
the location policy. Test first publication and rollback on staging. Enable a timer only after the real workload passes.
See [credential storage](security.md), [WordPress setup](wordpress.md), and the [capability matrix](platforms.md).
