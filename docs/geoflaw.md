# Geoflaw diagnostics

Public material inspected on 2026-11-16. Robert Beverly and Oliver Gasser announced
the beta [Geoflaw dashboard](https://geoflaw.cmand.org/) on NANOG under the subject
[Geoflow Geofeed Observatory](https://lists.nanog.org/archives/list/nanog@lists.nanog.org/thread/VXWTZ6LVR3FTNSFJ4HOU2TNDTYLWTGZJ/).
It reports reference, retrieval, content and coverage findings. This complements our
local checks. It is not a source of pool locations or an output/registration adapter.

## What it adds

| Finding | Operator action |
| --- | --- |
| Registry reference format | Check the actual registry field and exact public HTTPS URL |
| DNS, TLS, HTTP, encoding or plain-text retrieval | Check the anonymous public path, including hosting and edge behavior |
| RFC 8805 content | Compare the reported input and observation date with the exact current candidate |
| Missing covering reference or a different referenced URL | Review registry discovery scope separately from feed generation |

The inspected page describes a static snapshot with in-browser search. Its embedded
dates were 2026-11-11 for reference/retrieval/content and 2026-11-04 for coverage.
Those are dataset dates, not a live check of a feed viewed today. Counts describe reported
findings. No result does not establish validity, full coverage or provider ingestion.
No documented machine API or submission contract was verified. No source code or bulk
dataset was copied into this package, and no operator feed was submitted.

## Manual staging workflow

1. Check our normal source, ownership, allocation, location and publication results first.
2. Search Geoflaw by the exact public CSV URL and by relevant prefixes. URL-level content
   findings may not appear in a prefix-only search. Rich JSON is not an RFC 8805 geofeed.
3. Record each finding's dataset date and reproduce it against the current public route.
   Do not override a guard or change a pool location based only on an external finding.
4. Confirm the registry's reference and scope. A syntactically valid CSV can still be
   undiscoverable for part of its address space.
5. Keep this evidence separate from local verification and a provider's actual ingestion.

[RFC 9632 sections 3 and 4](https://www.rfc-editor.org/rfc/rfc9632.html#section-3)
distinguish two reference forms. Use the registry-supported form, for example:

```text
geofeed: https://example.net/geofeed.csv
remarks: Geofeed https://example.net/geofeed.csv
```

These are alternatives, not instructions to add both. If both exist on one object,
the native `geofeed:` attribute takes precedence. The remarks token has different
case/colon rules from the native attribute. Consumers use the most-specific referring
registry object. For unsigned feeds, they must ignore rows outside that object's range.
A row outside all objects referring to its feed is therefore not discoverable through
those references. That discovery step is separate from longest-prefix
locations inside a feed. A different referenced URL does not itself prove different
ownership. Registry administrative geography must not replace the operator's pool location.

## Planned integration

The initial [offline registry checker](registry-reference-checks.md) now compares a
supplied unsigned CIDR snapshot with a CSV candidate. It keeps exact discovery coverage
separate from local geography and reports live registry/provider checks as not measured.
It does not scrape Geoflaw or fetch the references in that snapshot.

[Issue #70](https://github.com/MHammett/isp-geofeed-generator/issues/70) tracks a safe
diagnostic workflow, dated findings and reference/coverage checks. It must distinguish
findings, no finding and not measured. Any exported-input adapter needs bounds and
sanitization and must not follow arbitrary URLs. The beta dashboard will not become a
required publication gate or be scraped on every scheduled run. Registry writes and
provider registration remain separate operations. Contributions with current public
contracts and sanitized operator results are welcome.

Any future registry lookup must stay within the operator's requested objects. RFC 9632
recommends registry bulk data for large-scale retrieval and discourages bulk RDAP use.
This tool will not scan address space through WHOIS or turn a targeted check into a crawl.
