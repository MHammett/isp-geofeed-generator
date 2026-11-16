# NetBox location models

NetBox supports several sound ways to store location data. Choose one explicitly with
`source.location_mode`. Do not remodel an existing instance solely to fit the default.

| Mode | Geography comes from | Extra reads |
| --- | --- | --- |
| `site`, the default | Prefix site/location scope and Site custom fields | Sites, plus Locations when used |
| `prefix_fields` | The prefix's own custom fields | None beyond prefixes and IP ranges |
| `region_hierarchy` | The scoped Region's exact ISO country/state/city chain | Regions |

All modes use the same tag/ID, status, VRF, owned-space, fullbogon and output guards.
The chosen model is authoritative; the adapter does not blend geography from other modes.
Within the chosen model, conflicting country/subdivision values or scope references fail.
Default site/location behavior and private `site_locations` overrides remain supported.

## Prefix custom fields

Set `location_mode: prefix_fields`. The default custom field names are `geofeed_country`,
`geofeed_region` and `geofeed_city`. Configure the exact API field names if they differ.
Choice fields use their stored `value`, not a display label. Field names must be simple
ASCII names of up to 64 characters, starting with a letter.

For existing GeoBox fields, the source portion of private configuration can be:

```yaml
source:
  type: netbox
  location_mode: prefix_fields
  tag: geofeed
  location_fields:
    country: geoloc_country
    region: geoloc_region
    city: geoloc_city
  location_enabled_field: geoloc_has_location
```

Keep URL, protected credentials, allowed allocations and output settings in the rest of
your normal private configuration. These settings also work inside each named input's
`source` section. Prefix/range read permission is enough for this mode; it does not read Sites.

If `location_enabled_field` is configured, every selected prefix must have boolean `true`.
False, absent or malformed flags stop publication. They do not emit a blank-location row
or silently withdraw a prefix. Remove an unwanted prefix from selection deliberately and
review any withdrawal before publishing. Do not map this setting to a text/choice field.

GeoBox can inherit blank fields from a parent prefix. This adapter does not. Every selected
prefix needs explicit geography or a reviewed private override. The synthetic location ID
is `prefix:<native-id>`, so a private override uses, for example, `site_locations["prefix:1"]`.
Such an override cannot bypass an invalid custom-field structure or disabled location flag.
Selecting nested prefixes is still refused under the current overlap policy.

## Region hierarchy

[NetBox supports Region-scoped prefixes](https://netboxlabs.com/docs/netbox/models/ipam/prefix/)
and [nested Regions](https://netboxlabs.com/docs/netbox/models/dcim/region/). In this mode,
declare this exact three-level meaning through the names:

```text
US
└── US-IL
    └── Example City
```

Country and state names must be assigned ISO codes. The city is the intended coarse city
name. Scope each intended prefix to that city Region. Set:

```yaml
source:
  type: netbox
  location_mode: region_hierarchy
  tag: geofeed
```

Grant prefix/range and Region read permissions. This mode does not read Sites or Locations.
It needs NetBox 4.2 or later for generic Region scope. It does not guess that a node named
“United States” means `US`, use a slug as a code, or geocode a name/address. More/fewer levels,
missing parents, cycles, invalid names and conflicting scope IDs stop selected records.
An instance with other Region conventions can use prefix-field or site mode instead.

The synthetic location ID is `region:<city-region-id>`. A private location override can
use that ID after the hierarchy resolves. An override does not bypass a malformed chain.
`source.location_fields` and `location_enabled_field` do not apply to this mode.

## IP ranges, selection and migration

A range uses the most specific containing prefix in the same VRF, interpreted in the
chosen mode. It does not read geography from the range itself or fall back to a broader
prefix when the closest one is incomplete. Equally specific duplicate parents fail.
Selecting both a containing prefix and its child range still causes an overlap failure.

Discovery retains unresolved unselected records and their error. Selected unresolved
records stop the whole run; none are silently discarded. A required named-input failure
also stops the combined feed. This is an adapter/setup limit, not a claim that NetBox
cannot represent the required data.

Keep the schedule stopped during migration. Save the prior config and feed, discover the
new model, generate a private candidate and compare prefixes and locations. A changed
location can trigger the normal review guard. An explicit mode does not bypass that guard.
Use exact-candidate approval only after review, then verify public delivery. To recover,
restore the saved source configuration and use the normal guarded publisher; preserve
the existing feed and backup until recovery is verified.

Alternate models are fixture-tested, including CLI and installed-wheel workloads. A real
instance using either model has not been measured. The default site's earlier live 4.7.3
read does not establish live coverage of these modes. No prior-art implementation was copied.
GeoBox's field schema is MIT. The unlicensed Region exporter was used only as a description
of the operator's data model; its skip-on-error, inheritance and aggregation behavior is not adopted.
