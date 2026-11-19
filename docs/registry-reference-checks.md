# Offline registry-reference coverage checks

`check-registry` compares a local CSV candidate with an operator-supplied registry
snapshot and an exact public feed URL. It reads no tool configuration, input platform
or credential. It does not fetch a URL, query a registry, change a registration, publish
a feed, or write status/recovery files. JSON results go to stdout only.

Generate and verify the candidate through the normal source, ownership and current
fullbogon checks first. This separate diagnostic does not repeat live allocation checks.
Use the stable public CSV URL, not a temporary probe or a URL containing credentials.

The default input is the normalized snapshot below. Initial
[saved RIPE REST JSON support](ripe-registry-input.md) is also available with
`--registry-format ripe-rest` and an explicit `--registry-observed-at`. Repeat
`--registry-records` for multiple files. RIPE requires one date per file in the same
order; normalized files keep their embedded dates. See the
[multi-file guide](ripe-registry-input.md#more-than-one-response) for combined limits,
duplicate refusals and per-input report fields. Support stays
offline and uses the same exact coverage and reference rules.

Initial [saved RDAP network support](rdap-registry-input.md) uses
`--registry-format rdap`, with one actual observation date per saved reply. It reads
standard geofeed links and distinguishes an absent link from unknown availability.
It performs no registry lookup or bootstrap authority check.
For replies with language alternatives, the RDAP guide documents the explicit
`--rdap-language` option and its supported tag subset. It has no automatic fallback.

The separate [saved-IANA planner](rdap-bootstrap-planning.md) selects a whole-prefix
RDAP lookup URL without contacting it. It does not authenticate the bootstrap file
or turn a comparison into proof of authority.
For one explicit live read, [capture-rdap](rdap-capture.md) saves an original reply
and actual observation receipt in a new restricted folder. It does not run this
comparison, follow referrals, fetch a feed or change publication state.

In Bash on Linux:

```bash
isp-geofeed-generator check-registry --registry-records /etc/isp-geofeed-generator/registry.json --feed /var/lib/isp-geofeed-generator/candidate.csv --feed-url 'https://example.net/geofeed.csv'
```

In PowerShell on Windows:

```powershell
isp-geofeed-generator check-registry --registry-records 'C:\ProgramData\ISP Geofeed Generator\registry.json' --feed 'C:\ProgramData\ISP Geofeed Generator\candidate.csv' --feed-url 'https://example.net/geofeed.csv'
```

The default CSV policy rejects overlaps. For an explicitly generated nested candidate,
add `--reference-policy longest_prefix`. It applies only to this diagnostic. It does
not configure a publisher. Other command flags and `--output` are refused; capture the
JSON through your shell into a separate private report if needed. `--config` is not read.

## Snapshot contract, initial support

Supply normalized JSON with exactly `schema_version`, `observed_at` and `objects`.
`schema_version` is integer `1`. `observed_at` is the export's actual UTC observation
time, in `YYYY-MM-DDTHH:MM:SSZ` or `+00:00` form. Future dates are refused. The report
keeps the supplied date and age; it does not assume an old export reflects current state.

Each object has:

| Field | Meaning |
| --- | --- |
| `id` | Unique stable export ID, 1–128 ASCII letters, digits, dots, underscores, colons or hyphens |
| `prefix` | Exact canonical IPv4/IPv6 CIDR scope. Use this or the `start`/`end` pair, never both. |
| `start`, `end` | Alternative exact inclusive address bounds of one registry object. Both are required, in the same address family, with `start` no greater than `end`. |
| `geofeed` | Optional native attribute value, consisting of one HTTPS URL. Omit when absent. |
| `remarks` | Optional array of at most 20 single-line strings, containing attribute values without the `remarks:` label |

For example, an object can contain `geofeed: https://example.net/geofeed.csv`, or its
remarks array can contain `Geofeed https://example.net/geofeed.csv`. These describe
the two distinct [RFC 9632 reference forms](https://www.rfc-editor.org/rfc/rfc9632.html#section-3).
The JSON keys represent the attributes; do not put the attribute labels in the values.
Do not include credentials, customer locations or administrative geography fields.

For a non-CIDR object, retain its exact inclusive bounds:

```json
{
  "id": "example-allocation",
  "start": "11.22.33.1",
  "end": "11.22.33.254",
  "geofeed": "https://example.net/geofeed.csv"
}
```

That example covers 254 addresses. A candidate `/24` still has two uncovered addresses.
Single-address ranges are allowed. IPv6 uses canonical compressed lowercase text,
without a zone ID. Address bounds are capped at 45 characters each. Do not put a CIDR,
an attribute label or a combined `a - b` string into either address field.

This initial format supports unsigned feeds and exact CIDR or address-range scopes.
It is not a WHOIS/RDAP parser. Signatures, same-scope tie resolution and multiple
remarks references need further support. Do not widen a real object, invent IDs or
split one object into CIDRs to make it fit. Splitting changes which object appears
most specific and can change discovery precedence. Format limits do not establish
whether the source platform can model the data.

## What is compared

A native reference takes precedence over remarks on that object. A child without a
reference does not shadow a referring parent. The most-specific referring scope applies
to each address. That choice is separate from location overrides within the CSV.
The checker clips unsigned feed coverage to the supplied referring scopes, counts
overlapping feed rows once, and keeps IPv4/IPv6 counts exact as decimal strings.

Referring scopes must be disjoint, equal, or wholly contained in one another. The
smallest containing object then has an unambiguous place in that hierarchy. CIDRs
and exact ranges use the same bounds; equal bounds remain a tie even when one is a
CIDR and the other is a range. Two inclusive ranges that share only one endpoint
overlap at that address. If they cross without containment, the whole command exits 1
with `crossing referring scopes` and produces no comparison report. This also applies
to crossing references outside the candidate. Correct the export or inspect the
registry hierarchy; do not truncate, widen or drop an object to force a pass.

An object with no reference does not participate in reference precedence. Its syntax
is still checked. The containment check and coverage sweep use range boundaries,
not address enumeration, including for large IPv6 ranges.

Reports include `registry_scope_formats` counts for `cidr` and `address_range` objects.
The `scope` stays `supplied_unsigned_cidr_snapshot` for CIDR-only input and becomes
`supplied_unsigned_range_snapshot` when any address-range object is supplied. The
snapshot schema stays at version 1; older tool versions refuse these new fields.

It reports coverage in five categories: `this_feed`, `other_feed`, `unreferenced`,
`invalid_reference` and `ambiguous_reference`. A different URL is an exact-string
difference, not proof of different ownership; aliases require operator review.
Queries and fragments are retained for comparison. URLs are validated but never followed.

Malformed would-be references are conservatively marked invalid instead of guessing a
consumer's fallback. Same-scope objects and multiple remarks references are reported as
unsupported ambiguity, even if a richer registry export could resolve them. Invalid or
unsupported selected objects make the comparison inconsistent. Structural errors stop
the command without echoing their values.

Input is bounded to 8 MB and 50,000 objects; CSV remains capped at 1 MB and 50,000 rows.
Duplicate JSON keys, nonfinite constants, unsafe IDs and control characters are refused.
The project's CSV parser still checks static special/bogon space and ISO location codes.
It accepts the project's generated format and uniform legacy LF, not arbitrary comments
or RPKI-signed feeds. No metadata changes the feed's locations.

Detailed findings and uncovered intervals are capped at 1,000 each. Truncation is explicit,
and full counts still decide the result. Reports contain IDs, ranges, hashes and dates,
but no CSV, location values or raw URLs. Keep inventory and reports private.

## Meaning of a result

Exit 0 and `comparison_consistent: true` mean only that the supplied snapshot supports
the exact URL for all candidate address coverage, without unresolved findings. They are
not a publication-health or ownership claim. Missing coverage, invalid references or
unsupported ambiguity exit 1. An empty snapshot never passes a nonempty candidate.

Live registry reads, ownership, signatures, current allocation, public retrieval and
provider ingestion remain `not_measured`. Validate them separately before deployment.
A stale or incomplete export can miss a newer, more-specific reference.

[Issue #70](https://github.com/MHammett/isp-geofeed-generator/issues/70) stays open for
additional snapshot forms, verified registry reads and safe Geoflaw findings import.
No beta dashboard becomes a publication gate, and no bulk lookup or automatic registry
write is performed. Contributions with public contracts and sanitized fixtures are welcome.
