# Saved RIPE registry input, initial support

The offline registry checker can read a saved RIPE REST JSON response without
rewriting it into the normalized snapshot format. It does not contact RIPE, follow
links, read credentials or change a registration. This is initial support based on
the public API contract and synthetic controls. Operator export testing is welcome.

Use an address-only response containing `inetnum` or `inet6num` objects from the
`RIPE` source. Keep the original file private. It can contain registry contact data
that the report does not need. Do not paste it into an issue; use a sanitized example.

Generate and verify the local CSV through the normal ownership, allocation and
fullbogon checks first. This diagnostic does not repeat live allocation checks.

## Run the comparison

Replace the date placeholder with the export's actual UTC observation time.

In Bash on Linux:

```bash
isp-geofeed-generator check-registry --registry-format ripe-rest --registry-records /etc/isp-geofeed-generator/ripe-response.json --registry-observed-at 'YYYY-MM-DDTHH:MM:SSZ' --feed /var/lib/isp-geofeed-generator/candidate.csv --feed-url 'https://example.net/geofeed.csv'
```

In PowerShell on Windows:

```powershell
isp-geofeed-generator check-registry --registry-format ripe-rest --registry-records 'C:\ProgramData\ISP Geofeed Generator\ripe-response.json' --registry-observed-at 'YYYY-MM-DDTHH:MM:SSZ' --feed 'C:\ProgramData\ISP Geofeed Generator\candidate.csv' --feed-url 'https://example.net/geofeed.csv'
```

The date accepts UTC seconds with `Z` or `+00:00`. Future dates are refused. Do not
substitute an object's `last-modified` value, a file's modification time or the time
you ran this command for the actual export observation time. The report labels the
date as operator supplied; it does not verify it. As with normalized snapshots,
age is reported without imposing a maximum age.

The existing `--reference-policy longest_prefix` option permits an explicitly
generated nested candidate. No publication policy is configured by this command.
`--output` and publication/recovery flags remain refused. `--config` is not read.
The default `--registry-format normalized` keeps the existing snapshot contract and
uses the date inside that snapshot; a separate observation date is refused there.

## Supported saved response

[RIPE's data model](https://docs.db.ripe.net/RIPE-Database-Structure/REST-API-Data-model/)
describes the `objects.object` list, object type/source, primary key and named
attribute values. A synthetic IPv4 example is:

```json
{
  "objects": {
    "object": [{
      "type": "inetnum",
      "source": {"id": "ripe"},
      "primary-key": {
        "attribute": [{"name": "inetnum", "value": "11.22.33.1 - 11.22.33.254"}]
      },
      "attributes": {
        "attribute": [
          {"name": "inetnum", "value": "11.22.33.1 - 11.22.33.254"},
          {"name": "source", "value": "RIPE"},
          {"name": "geofeed", "value": "https://example.net/geofeed.csv"}
        ]
      }
    }]
  }
}
```

That scope covers 254 addresses, so a `/24` candidate has two uncovered endpoints.
The reader does not widen the range or split one registry object into CIDRs.
`inet6num` uses its exact canonical IPv6 prefix instead. Each primary key must match
the object's address attribute. Duplicate scopes from the same source are refused
as duplicate objects, rather than silently choosing one version.

Native `geofeed` values and remarks go through the existing
[reference and precedence checks](registry-reference-checks.md). Invalid native
references still block fallback. Administrative `country`, `geoloc`, descriptions,
contacts and unrelated attributes do not supply feed locations and are not copied
into the report. Response links are never fetched.

Each safe object ID contains its type and a SHA-256 digest of its exact scope.
The report labels `registry_input_format` as `ripe-rest` and `registry_source` as
`RIPE`. It hashes the original file in `snapshot_sha256` and the internal normalized
snapshot in `normalized_snapshot_sha256`. Contact data and raw reference URLs are
not printed. These labels and hashes describe supplied data, not its authenticity.

## Refusals and limits

The saved file is limited to 8 MB and 50,000 objects. Each object has at most 200
attributes. Names are bounded lowercase attribute names; values must be strings
with at most 8,192 characters and no line controls. The shared checker further
limits remarks to 20 lines of at most 2,048 characters. Duplicate JSON keys,
non-finite numbers, empty responses and API messages are refused. Even a warning
or informational API message stops comparison; it must not be mistaken for a
complete successful export. Raw messages are not logged.

Only RIPE address objects are supported initially. Other sources, related person
or route objects, duplicate native attributes, mismatched keys, unsupported scope
syntax and malformed containers stop the whole comparison. They are not silently
dropped. Obtain an appropriate address-only export or use the existing reviewed
normalized format. These are reader limits, not claims that RIPE or another
registry cannot model that data.

Correct the source/export while leaving the feed and its status/recovery files
untouched. Retry this read-only comparison after checking the corrected input.
A refusal does not change or repair a registry record or publication.

## What a successful comparison does not prove

All [existing diagnostic limits](registry-reference-checks.md) still apply. The report
has no publication health flag. Live registry reads, current allocation, ownership,
signatures, public delivery and provider ingestion remain `not_measured`.

[RIPE documents](https://docs.db.ripe.net/How-to-Query-the-RIPE-Database/RESTful-API-Queries/)
that a lookup returns the specific requested object and does not return an enclosing
object when the exact object is absent. A parent-only export cannot reveal an omitted
child that points elsewhere. Operators must include the relevant referring hierarchy;
the checker cannot prove export completeness from a local file. Do not claim that
`comparison_consistent` establishes all registry discovery paths.

Any future targeted lookup must stay within requested objects. Keep large retrieval
separate, following [RFC 9632's guidance](https://www.rfc-editor.org/rfc/rfc9632.html#section-4).
This reader does not crawl WHOIS, use RDAP in bulk or scrape Geoflaw. Signed feeds,
same-scope resolution and actual registry reads remain open under
[issue #70](https://github.com/MHammett/isp-geofeed-generator/issues/70).
