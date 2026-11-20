# Plan an RDAP lookup from saved IANA data

`plan-rdap` selects a service for one explicit IPv4 or IPv6 prefix using a saved
IANA address bootstrap file. It prints a lookup plan. It makes no DNS or HTTP request,
reads no configuration or credential, and writes no file. It does not query a registry,
fetch a feed, publish, or change status and recovery files. Support is initial.

This helps choose where a later lookup belongs. A registry's location does not locate
customer addresses. A plan also does not establish ownership, current allocation,
server availability, geofeed support or provider ingestion.
The separate [capture command](rdap-capture.md) can make one explicit lookup and
preserve its original bytes and observation receipt. Planning itself remains offline.
The IANA entry point may redirect or refer a later lookup to another service. This
planner neither follows nor verifies that handoff. A planned URL does not make a
later policy-truncated reply usable by the saved-RDAP checker.

## Supply a dated source

Obtain the original [IANA IPv4 bootstrap](https://data.iana.org/rdap/ipv4.json) or
[IANA IPv6 bootstrap](https://data.iana.org/rdap/ipv6.json). Keep the complete reply
and record its actual UTC download time. The file must match the requested address
family. Do not merge families, invent entries or drop services to force a result.

Replace the date placeholder below with that observation time. The file's declared
`publication` time is a different fact. An unchanged old publication can be freshly
downloaded. Do not substitute a file modification time or a registration event date.

In Bash on Linux:

```bash
isp-geofeed-generator plan-rdap --bootstrap-records /etc/isp-geofeed-generator/iana-ipv4.json --bootstrap-observed-at 'YYYY-MM-DDTHH:MM:SSZ' --rdap-prefix '11.22.33.0/24'
```

In PowerShell on Windows:

```powershell
isp-geofeed-generator plan-rdap --bootstrap-records 'C:\ProgramData\ISP Geofeed Generator\iana-ipv6.json' --bootstrap-observed-at 'YYYY-MM-DDTHH:MM:SSZ' --rdap-prefix '2001:4860:1234::/48'
```

Use your own requested prefix. These are public format examples, not allocation or
ownership claims. The prefix must be canonical and outside the shared static
special-use ranges. The planner does not refresh fullbogon data or verify current
allocation. Generation and publication still require their normal current fullbogon
and ownership checks. A successful plan cannot replace those guards.

## Whole-prefix selection

[RFC 9224 section 5](https://www.rfc-editor.org/rfc/rfc9224.html#section-5) defines
longest-prefix matching. The planner applies that choice at every part of the
requested prefix. A nested entry can override a covering parent. Adjacent scopes
can form complete coverage when they select the same service. A parent fully
shadowed by children does not decide the result.

Gaps or more than one selected service stop the entire plan. Choosing only from the
first address could send part of a prefix to the wrong service. The calculation uses
range boundaries, not address enumeration, including for IPv6. If services differ,
inspect the source and request separate narrower scopes. No split, crawl or retry
happens automatically.

[RFC 9082 section 3.1.1](https://www.rfc-editor.org/rfc/rfc9082.html#section-3.1.1)
defines the IP lookup path. The planner appends `ip/` and the canonical requested
prefix to the selected base. It never reads a URL from description text or follows
the planned URL.

## Initial profile and limits

The current profile supports these exact HTTPS RIR bases, checked against the public
IANA address files on 2026-11-19:

- `https://rdap.afrinic.net/rdap/`
- `https://rdap.apnic.net/`
- `https://rdap.arin.net/registry/`
- `https://rdap.db.ripe.net/`
- `https://rdap.lacnic.net/rdap/`

An entry may also list the same base's legacy HTTP counterpart. HTTPS is selected
regardless of order. HTTP-only entries, more than one HTTPS alternative, unknown
bases, changed paths, credentials, query strings and fragments are refused. There
is no insecure fallback. Unsupported services may be valid; they need further reader
support and tests. This is not a claim that another platform lacks RDAP capability.

The profile supports bootstrap version `1.0`. Limits are 1 MB of original JSON,
100 service groups, 4,096 total prefixes, eight URLs per group, 256 characters per
URL and 128 characters per prefix. All authority prefixes must be canonical and of
the requested family. Equal prefixes are refused even if their URLs match; this
initial reader does not resolve equivalent-entry ties. Invalid unrelated authority
rows also stop the plan. Keep the original file and investigate the source.

Duplicate JSON keys, non-finite numbers, invalid encoding, excessive nesting and
malformed required fields are refused. Unused metadata is ignored and never executed
or printed. Dates use UTC `Z` or `+00:00`, with up to six fractional digits. Future
dates and a publication later than the supplied download time are refused. Those
format limits are not a complete implementation of every possible future bootstrap.

## Read the result

The report retains the original SHA-256, supplied observation date and age, declared
publication date and age, route counts, requested prefix and planned HTTPS URL.
It labels the source `operator_supplied_iana_bootstrap` and the result
`single_service_for_entire_prefix`. Input paths and descriptions are omitted.

`planning_only` and `inspection_only` are true. There is no `healthy` field.
Bootstrap authenticity, live registry reads, ownership, current allocation,
signatures, public feed retrieval and ingestion remain `not_measured`. A hash binds
the report to supplied bytes; it does not authenticate those bytes or detect an
unmarked partial export whose missing entries are hidden by a broader route.

Any later lookup must record its own response time and original reply. The bootstrap
download time is not the RDAP response observation time. The existing
[saved-RDAP checker](rdap-registry-input.md) remains a separate read-only step.
This planner's flags are refused on publication and other commands. `--output` and
registry comparison flags are refused on the planning command too.

On refusal, retain the file and inspect its origin, scope and supported format.
Existing feed/status/recovery files stay intact. Omitting `plan-rdap` returns to the
existing saved-response workflow; no data, hosting or credential migration is needed.
Contributions and sanitized examples are welcome. Remaining discovery work is tracked
in [#70](https://github.com/MHammett/isp-geofeed-generator/issues/70); this planner is
tracked in [#103](https://github.com/MHammett/isp-geofeed-generator/issues/103).
