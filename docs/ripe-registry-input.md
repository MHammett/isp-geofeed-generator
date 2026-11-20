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

The date accepts UTC seconds with `Z` or `+00:00`, optionally with one to six
fractional digits. That precision is retained. Future dates are refused. Do not
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

### Obtain an address-only result

A default RIPE search can include organisation and role objects, which this reader
refuses. For an operator-chosen IPv4 prefix, the request shape is:

```http
GET https://rest.db.ripe.net/search.json?source=ripe&type-filter=inetnum&flags=no-referenced&flags=no-irt&flags=all-less&query-string=<URL-encoded-owned-prefix>
```

Use `type-filter=inet6num` for IPv6. `no-referenced` and `no-irt` keep related contact
objects out. `all-less` requests parents. Request children separately with `all-more`
instead of `all-less`. These are request shapes for the operator's chosen objects,
not a command to scan address space. See the [RIPE query contract](https://docs.db.ripe.net/How-to-Query-the-RIPE-Database/RESTful-API-Queries/).

[Claude tested these forms](https://github.com/MHammett/isp-geofeed-generator/pull/89#pullrequestreview-5961315620)
using saved public responses for RIPE NCC's own IPv4 and IPv6 blocks. Default searches
with contacts were refused; address-only parent results were accepted. An `all-more`
query with no children returned an API error and was refused. A successful HTTP status
alone is insufficient: RIPE documents that a streamed search can carry errors in its
JSON body. Do not remove those messages just to force a comparison.

### More than one response

Repeat `--registry-records` for each saved response. Add one `--registry-observed-at`
for each RIPE file, in the same order. One date is never copied to several files.
Keep each file's actual observation time, even when the responses were collected
on different days. All files in one command must use the chosen format.

In Bash on Linux:

```bash
isp-geofeed-generator check-registry --registry-format ripe-rest --registry-records /etc/isp-geofeed-generator/ripe-v4.json --registry-observed-at 'YYYY-MM-DDTHH:MM:SSZ' --registry-records /etc/isp-geofeed-generator/ripe-v6.json --registry-observed-at 'YYYY-MM-DDTHH:MM:SSZ' --feed /var/lib/isp-geofeed-generator/candidate.csv --feed-url 'https://example.net/geofeed.csv'
```

In PowerShell on Windows:

```powershell
isp-geofeed-generator check-registry --registry-format ripe-rest --registry-records 'C:\ProgramData\ISP Geofeed Generator\ripe-v4.json' --registry-observed-at 'YYYY-MM-DDTHH:MM:SSZ' --registry-records 'C:\ProgramData\ISP Geofeed Generator\ripe-v6.json' --registry-observed-at 'YYYY-MM-DDTHH:MM:SSZ' --feed 'C:\ProgramData\ISP Geofeed Generator\candidate.csv' --feed-url 'https://example.net/geofeed.csv'
```

The first date belongs to the first records file; the second date belongs to the
second file. Replace both date placeholders with the actual dates. A mismatch in
the number of files and dates stops before any file is read. With normalized input,
repeat the records option without separate date options; each file has its own date.

The reader combines exact scopes and references before one coverage comparison.
A child from a separate file can still override a parent reference. Duplicate object
IDs stop the whole comparison, including identical copies and newer versions of the
same RIPE key. The tool does not choose a winner or silently remove copies. Parent
and child query results can overlap; obtain a set without repeated objects, or use a
separately reviewed normalized snapshot. Different IDs for the same referring scope
remain unsupported ambiguity. Crossing referring scopes remain a refusal.

#### Avoid shared parents for prefixes in one allocation

Running `all-less` once per customer prefix repeats shared parent objects. For several
prefixes inside one operator-chosen covering allocation, query that covering block
once with `all-less` and once with `all-more`. Keep the same source, address family,
type filter and query range in both requests. Save the replies as separate files,
for example `parents.json` and `children.json`:

```http
GET https://rest.db.ripe.net/search.json?source=ripe&type-filter=inetnum&flags=no-referenced&flags=no-irt&flags=all-less&query-string=<URL-encoded-owned-covering-prefix>
GET https://rest.db.ripe.net/search.json?source=ripe&type-filter=inetnum&flags=no-referenced&flags=no-irt&flags=all-more&query-string=<URL-encoded-owned-covering-prefix>
```

Use `inet6num` in both requests for IPv6. RIPE's
[query table](https://docs.db.ripe.net/Tables-of-Query-Types-Supported-by-the-RIPE-Database)
states that `all-less` includes an exact match and its parents, while `all-more`
returns smaller ranges and excludes that exact match. This separates the two sets
without dropping an object. Supply both files with their own observation dates using
the repeated records/date options above.

[Claude tested this recipe](https://github.com/MHammett/isp-geofeed-generator/pull/92#pullrequestreview-5964452587)
on public RIPE NCC records: two parent objects and eight child objects passed the CLI.
Claude also verified that a child reference in a separate file wins in either file order.
These are Claude's reported checks, not a live verification of an operator's allocation.

Keep requests within the chosen allocation and the reader's combined budgets. Do
not expand the query to all address space to avoid shared parents. Different
covering allocations can still share ancestors; this recipe does not automatically
resolve that case. Concurrent changes can also prevent separately saved files from
forming one current view. Duplicate IDs and API messages remain refusals. An error
reply, including a no-entries reply, must not be stripped or presented as a successful
empty export. Inspect the source set or prepare a separately reviewed normalized
snapshot; the checker cannot prove hierarchy completeness from these files.

If any file is missing, malformed, over budget or contains API messages, no partial
report is printed. Retain the original responses. Correct the input set and rerun
the read-only comparison; feed, status and recovery files stay untouched.

Multi-file reports include `snapshot_input_count` and `snapshot_inputs`. Each input
has its ordinal number, original and normalized hashes, observation date, age and
object count. Paths, contacts and raw reference URLs are not printed. The top-level
date is the oldest input date, labeled `oldest_supplied_input`. It is not a claim that
all files describe one instant or that the set is current or complete.

For multiple files, `snapshot_sha256` and `normalized_snapshot_sha256` hash the
combined normalized snapshot; `snapshot_sha256_scope` states that meaning.
`source_manifest_sha256` hashes the ordered per-input metadata without the age
fields. It stays stable when only time passes. Original hashes remain in
`snapshot_inputs`. Single-file reports keep their existing fields and hash meanings.
The files are read separately, not as an atomic filesystem snapshot. Each read keeps
the existing regular-file, no-final-symlink, size and read-time identity guards.

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
`RIPE`. For a single input, it hashes the original file in `snapshot_sha256` and the
internal normalized snapshot in `normalized_snapshot_sha256`. For multiple files,
use the combined and per-input hash fields described above. Contact data and raw reference URLs are
not printed. These labels and hashes describe supplied data, not its authenticity.

## Refusals and limits

One command accepts up to 32 saved files. Their total original bytes and the combined
normalized snapshot must each fit within 8 MB. The total object count is at most
50,000, across the whole set. These are combined limits, not a fresh budget per file.
Each object has at most 200 attributes. Names are bounded lowercase attribute names; values must be strings
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
