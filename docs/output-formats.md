# Location fields and output formats

Inputs return exact IP coverage and site records. The core selects and validates only
the location fields requested by the output. A target declares its accepted fields,
required fields and payload format. A field that the target cannot accept stops the run.
Missing requested values stop the run. Latitude and longitude must be selected together.
The core never invents coordinates from a city or guesses a city from coordinates.

| Output | Fields | Payload |
| --- | --- | --- |
| `file`, `wordpress` | Country, region, city | RFC 8805 CSV; postal column stays empty |
| `json` (initial support) | Any supported field selection | Normalized location-record JSON version 1 |
| Installed target extension | Its declared supported and required fields | CSV bytes or normalized records for its own serializer |

CSV keeps the existing policy: country and city are required, and region can be empty.
Rich fields are `country`, `region`, `city`, `latitude`, `longitude`, `postal_code` and
`accuracy_km`. Coordinates must be finite numbers in range; booleans are refused.
Accuracy is a nonnegative radius in kilometers, supplied by the operator or input.
Strings reject control characters. Country and region code shapes are checked, but
complete ISO code membership is still tracked in issue #18.

For a coordinate-only JSON file, use this publication section in a complete private config:

```yaml
publish:
  type: json
  path: /var/lib/isp-geofeed-generator/public/locations.json
  location_fields: [latitude, longitude]
  allow_initial: false
```

Generate and test the candidate, then set `publish.allow_initial: true` for a publication
trial. A normalized document looks like this (the prefix below is documentation only):

```json
{"schema_version":1,"records":[{"prefix":"192.0.2.0/24","location":{"latitude":41.9,"longitude":-88.7}}]}
```

Use `site_locations` to supply reviewed fields for a source that does not expose them.
For gaiia, `source.include_coordinates: true` explicitly requests native site coordinates.
It defaults to false. Requesting coordinates from the source does not publish them unless
the output selects those fields. Choose a location policy suitable for public disclosure;
do not use customer premises data by accident.

The JSON target validates canonical records, keeps prior bytes, checks address withdrawal
limits and reads back the written file. It proves local bytes only. It is not a GeoIP
provider API or a standard geofeed discovery format. Provider integrations and registration
workflows are tracked in [issue #24](https://github.com/MHammett/isp-geofeed-generator/issues/24).
[Location-change limits](location-changes.md) compare the actual published fields, including
coordinates and profile changes, before writing either output format.

Extension authors set `TargetAdapter(payload_format='records', location_fields=...,
required_fields=...)` with frozensets of supported field names. Required rich fields must
have nonempty values; numeric zero is valid. The target receives normalized records and
owns provider-specific units, encoding and read-back. See [adapter contracts](adapters.md).
