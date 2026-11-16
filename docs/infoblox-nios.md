# Infoblox NIOS: initial network input

This source uses the public NIOS WAPI 2.13.6 contract checked on 2026-11-16.
The [vendor manual](https://docs.infoblox.com/download/attachments/15433773/Infoblox%20NIOS%20WAPI%209.x%20Reference%20Guide.pdf)
documents network reads, opaque references, extensible attributes and paged results.
It is the on-premises NIOS API family. Infoblox cloud products are separate adapters.
No live NIOS instance has been queried. Contributions and sanitized operator feedback
are welcome. This source stays labeled initial support until other operators test it.

## Declare the instance's location model

Choose which entire networks belong in the geofeed. Supply coarse geography through
three string extensible attributes or explicit private location overrides. Default names
in this adapter are `geofeed_country`, `geofeed_region` and `geofeed_city`. They are an
operator setup convention, not attributes the platform creates automatically. Configure
other existing names through `source.location_fields`.

Use assigned ISO country and subdivision codes and the intended coarse city. No country
translation, geocoding, coordinate inference or free-text name join is performed.
The source uses the returned attribute `value`, including a value the platform resolves
through inheritance. It never fetches parents or invents missing inherited values.
Malformed declared attributes stop selected records even when an override exists.
Absent values may be supplied by a reviewed `site_locations` entry.

A network view identifies an address namespace. It is not a physical facility. This
adapter makes one synthetic location per network from the declared values. It does not
claim a native facility join. If your instance already models site metadata, map the
relevant attributes deliberately. Missing setup is not a missing platform capability.

## Endpoint, credentials and permissions

Use [the example](../config.infoblox-nios.yaml.example). Set `INFOBLOX_NIOS_URL` to the
complete HTTPS base ending in `/wapi/v2.13.6`. Other WAPI versions are refused by this
initial adapter because they are not verified here. That is an adapter limit, not a claim
that the platform lacks backward compatibility. For [named inputs](multiple-inputs.md),
use the input's `url` and explicit credential references instead of URL environment fallback.

Use [secure references](security.md) for `INFOBLOX_NIOS_USERNAME` and
`INFOBLOX_NIOS_PASSWORD`. The source uses HTTPS Basic authentication with normal TLS
certificate checks. Install the appropriate trusted CA using host policy; do not disable
verification. Certificate-based authentication is not implemented by this adapter.
Grant the dedicated account API access and only the required network/attribute reads.
Exact role settings must be checked on your release. No host records, subscriber data,
leases, DHCP options, provisioning writes or login/logout operations are requested.
The username cannot contain a colon. Secrets never belong in a URL or YAML value.

The API returns all extensible attributes for a network in this contract. Only the
three declared values are retained. Unrelated attribute values, comments, member lists
and other fields are discarded before discovery/status output. Discovery still contains
private network references, view names and inventory; protect it like other input exports.

## Discover and select

Temporarily use `source.network_refs: []` for discovery. It reads both network families;
failure to read either stops discovery. An empty family is recorded with count zero;
an entirely empty inventory is not reported as a measured success.

Copy the exact selected `source_id` references from discovery into `source.network_refs`.
References are opaque. Never edit their contents to infer an address or a site. Publication
requires a nonempty explicit selection, at most 10,000 references. When selected, only
the families containing those references are queried, and every selected record must be
visible. One missing record stops the run. The adapter does not silently publish the rest.

The normalized pool ID is `network:<sha256-of-reference>`. Its synthetic location ID is
`location:<same-digest>`. Use normalized IDs in `pool_sites` and `site_locations`; selection
uses the raw reference. Discovery reports both. Hashing bounds the identifier without
decoding or truncating the reference. A recreated record can have a new reference and
needs a reviewed selection/mapping update.

Equal prefix text in different views retains distinct identity. Selecting both still
triggers the normal duplicate/overlap refusal. Do not merge views by matching address text.
No DHCP range or network-container expansion is included. Whole selected networks are
published; this is not an export of assigned individual customer addresses.

## Paging and failure behavior

Paging stays on the configured endpoint. A continuation token is encoded as query data,
never followed as a URL. Repeated tokens, duplicate references, malformed pages, empty
intermediate pages, oversize pages and page-budget exhaustion stop the read. No more
than 50,000 records across the queried families are retained; exceeding that budget
stops the read. Raw page data is processed one page at a time. Declared values over 512
characters or containing controls are recorded as invalid and discarded. No automatic
retry is made after authentication failure, timeout or a later page failure. The API does
not supply a total count in this contract; successful paging is not proof of a transactional
snapshot or of visibility beyond the account's permissions.

Missing/wrong-family boundaries and invalid view/reference identity stop the inventory
read. Malformed geography is retained as an error in discovery and stops a selected
record. Missing selected location values stop generation unless explicitly supplied by
a reviewed override. Unselected geography errors are not silently promoted to output.

Keep all ownership, ISO, no-bogon, overlap and output change guards. Generate a candidate,
compare selection and view counts with the instance, and test public delivery and recovery
on staging. Then explicitly opt in with `source.allow_initial: true`. Fixtures and an
installed-wheel workload cover dual-stack output and failures; no live permission,
inheritance, paging or deployment behavior has been measured.

On source failure the CLI retains the feed and backup and records unhealthy status.
Keep the timer stopped while diagnosing access or data. Correct the selection, attributes
or reviewed override, generate again and verify before resuming. Follow the normal
[publication recovery](publication-verification.md) procedure if destination recovery is
needed. Never disable the guards to work around a missing source record.
