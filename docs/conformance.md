# Geofeed conformance and ISO codes

The publisher now checks country and subdivision membership, not only code shape.
`US` and `US-IL` pass. `XX` and `US-ZZZ` fail. A valid subdivision must also belong to
the chosen country. The same rules apply to CSV and selected rich JSON fields.
Coordinate-only output does not invent a country or check an unselected country field.

This project accepts assigned ISO 3166-1 alpha-2 codes and ISO 3166-2 subdivisions from
its pinned snapshot. It does not guess aliases or accept reserved, withdrawn or private
country codes. For example, use the reviewed assigned `GB` code rather than `UK`.
A blank region remains allowed. This is the project's publisher policy; RFC 8805 also
allows some optional features and exceptionally reserved codes that this tool does not emit.

## Data and updates

Both packages contain identical, unmodified ISO JSON data from Debian iso-codes as
distributed by pycountry at `4c6a69927a25326a69bf753671fb571bb437cd7d`.
The snapshot has 249 assigned countries and 5,046 subdivisions. Upstream's subdivision
file was updated to iso-codes 4.20.1 on 2026-01-21; its country file last changed on
2023-09-29. Those are source-history observations, not a promise that this is a live
copy of ISO's register. ISO remains the authority for the codes.

Runtime validation makes no network request. Both readers check file hashes and fail
closed if data is missing or changed. Full LGPL-2.1 license and copyright files travel
with the data. See [third-party notices](../THIRD_PARTY_NOTICES.md) and each `sources.json`
for the exact source URLs and checksums. No pycountry executable code is bundled.

Maintainers update the dataset through a reviewed PR. Fetch all four files from a new
immutable upstream revision. Preserve the original files and notices in both `iso_data`
folders. Update the source manifest, both readers' expected hashes/counts and verification
evidence. Run the full tests and installed-package checks. Do not patch an individual
code into one copy. Report a missing valid code with its ISO reference so the source
and release can be checked; do not disable membership validation.

## What independent checks measured

Observed on 2026-11-16 using synthetic local files. MaxMind v5.0.0 was checked against
its vendor archive manifest and pinned executable hashes. Candela's BSD-licensed source
was run at `ede8916ee1045fa806554bb76112d0fecc63b40d` using its runtime lockfile entries.
Install lifecycle scripts are disabled. A Node 24 loader handles its original module
imports without changing vendor source. Neither tool is a runtime
dependency of this publisher.

The full external development tree reported 12 audit findings. It is not installed by
the CI comparison. The runtime-only install contains 19 audited packages and reported
zero findings on 2026-11-16. CI reruns that audit and fails on findings. See issue #48.

| Control | This publisher | Candela | MaxMind, format only |
| --- | --- | --- | --- |
| Good LF/CRLF, Unicode and IPv6 | Accepts | No errors | No errors |
| Invalid prefix | Refuses | Reports errors | Reports errors |
| Invalid country/subdivision or mismatched country | Refuses | Reports errors | No errors |
| Duplicate prefix | Refuses | No errors | No errors |
| Nested prefixes | Refuses under current policy | No errors | No errors |
| Missing city, extra column or postal code | Refuses under current policy | No errors | No errors |

Nested prefixes and optional fields can be valid RFC input even though this publisher
uses stricter output rules. Do not call those external-tool results RFC defects.
Candela's per-line API is used to read its errors; its CLI may report errors while still
exiting zero. The test does not trust exit status alone for that tool. The comparison
uses 13 explicit controls and records each result. It does not certify every possible feed.
No MMDB, allocation-ownership or real customer-geography comparison was run.

The separate CI job stages an exact source revision and hash-pinned verifier binary,
then runs `tests/check_external_conformance.py`. The regular Python and PHP suites use
the same committed control file. A passing external format check cannot replace the
ownership, fullbogon, overlap, withdrawal, location-change or publication checks.

## Upgrade and recovery

Copy the whole WordPress plugin folder, including `iso_data` and its notices. A PHP-only
copy is incomplete and refuses new writes. The Python wheel and deployment plan also
include the data files. Follow the [plugin-first upgrade order](wordpress.md#line-endings-and-refresh-policy).

Before scheduling, check the existing feed as well as the new candidate. A feed with an
unrecognized code now stops validation. Fix the source or reviewed site override and
generate a private, valid candidate. A malformed old baseline is also refused, so normal
publication cannot silently replace an invalid feed and call it a verified recovery path.
For WordPress, use the [manual conditional recovery](wordpress.md#manual-rollback) with
the current stored hash and the reviewed valid candidate. For files, stop all writers,
retain the exact old bytes and use an operator-controlled atomic replacement of the
reviewed candidate. Check local bytes and public delivery before restarting the timer.

If the data files are damaged, reinstall the reviewed complete package/plugin. Do not
edit their checksums to make a corrupt installation pass. For a code rollback, use the
prior approved runner and matching plugin/configuration, after preserving current feeds
and recovery files. A package rollback does not approve a location move or withdrawal.
