# Saved RDAP network input, initial support

The offline checker can read saved RDAP IP-network lookup replies. This adds another
discovery format to [registry checks](registry-reference-checks.md). It does not
contact a registry, follow links, read credentials, change a record or publish a feed.
Support is initial. Contributions and sanitized operator export feedback are welcome.

Keep original replies private because they can contain contact data. Generate and
verify the candidate using the normal ownership and current fullbogon guards first.
This diagnostic does not repeat live allocation checks or verify the saved file's origin.

## Run a comparison

Save one top-level `ip network` reply per file. Replace each date placeholder with
the actual UTC observation time for that reply, not a registration event date.

In Bash on Linux:

```bash
isp-geofeed-generator check-registry --registry-format rdap --registry-records /etc/isp-geofeed-generator/rdap-v4.json --registry-observed-at 'YYYY-MM-DDTHH:MM:SSZ' --registry-records /etc/isp-geofeed-generator/rdap-v6.json --registry-observed-at 'YYYY-MM-DDTHH:MM:SSZ' --feed /var/lib/isp-geofeed-generator/candidate.csv --feed-url 'https://example.net/geofeed.csv'
```

In PowerShell on Windows:

```powershell
isp-geofeed-generator check-registry --registry-format rdap --registry-records 'C:\ProgramData\ISP Geofeed Generator\rdap-v4.json' --registry-observed-at 'YYYY-MM-DDTHH:MM:SSZ' --registry-records 'C:\ProgramData\ISP Geofeed Generator\rdap-v6.json' --registry-observed-at 'YYYY-MM-DDTHH:MM:SSZ' --feed 'C:\ProgramData\ISP Geofeed Generator\candidate.csv' --feed-url 'https://example.net/geofeed.csv'
```

Use one records/date pair for one reply. Repeated files use dates in the same argument
order. Missing dates or a count mismatch are refused. Invalid and future dates are
refused too. All inputs in a command use the selected format; mixed-format sets are
not implemented. Default normalized input and existing RIPE commands still work.

## Scope and link rules

[RFC 9083](https://www.rfc-editor.org/rfc/rfc9083.html#section-5.4) defines the network
object and its address bounds. The reader requires `objectClassName` of `ip network`,
a bounded handle, `startAddress`, `endAddress` and a matching `ipVersion`. It keeps
inclusive endpoints without rounding them to a CIDR. Valid IPv6 spellings become
canonical address text without changing their numeric bounds. Safe IDs hash the
handle and exact range; raw handles are not printed.

[RFC 9877](https://www.rfc-editor.org/rfc/rfc9877.html#section-2) defines the geofeed
link and `geofeed1` declaration. A root `links` entry containing the `geofeed` relation
token supplies the reference, including a space-separated relation list. It needs
an HTTPS `href` and a `value` context. This reader accepts
bounded HTTP/HTTPS contexts without credentials. The recommended `type` field may
be absent. If present, the initial reader supports `application/geofeed+csv` only,
case-insensitively and without parameters. Unsupported media types stop this reader;
that is not a claim that the registry cannot serve geofeed data.

The declaration and the link are separate. A geofeed link is accepted without
`geofeed1`. A missing declaration is not proof of missing service capability.
Reports distinguish the saved view with these fixed values:

| `rdap_link_status` | What was observed |
| --- | --- |
| `link_returned` | The supplied network object includes one supported geofeed link. |
| `not_returned_with_extension` | The reply declares `geofeed1` but returns no link for this object. |
| `availability_not_measured` | Neither the declaration nor a geofeed link was returned. |

`rdap_geofeed1_advertised` reports the exact declaration separately. These fields
describe supplied data. They do not establish current server state, authenticity,
permissions, privacy-related omissions or what an omitted parent/child would return.
Coverage called `unreferenced` means no applicable reference in the supplied set.
It does not mean the registry has no reference anywhere.

Only the current network's root links are used. Entity links, nested networks, free
text remarks and administrative country values do not locate customer addresses.
Self, parent and other URLs are never fetched. Obtain needed parent/child replies
separately; the checker does not prove that the set contains the complete hierarchy.
Known child references retain the shared most-specific scope rule across files.

## Refusals and bounds

One command accepts at most 32 files. RDAP initially supports one network object per
file, so it can compare up to 32 supplied RDAP objects. Shared limits also bound total
original bytes and the combined normalized snapshot to 8 MB each. Links are limited
to 200 per reply, conformance entries to 100 and root notices/remarks to 100 each.
Handles are limited to 256 characters, link targets and contexts to 2,048 characters.
Relevant strings must be single-line. Original JSON is also checked for duplicate
keys, non-finite numbers, invalid encoding and excessive nesting.

Errors and typed truncation in root notices/remarks stop the comparison.
Informational terms notices can remain. Free text is not parsed
to guess whether more data exists; an unflagged incomplete reply cannot be detected
from these files alone. Do not strip an error or truncation marker to force a pass.

### Contact redaction

[RFC 9537](https://www.rfc-editor.org/rfc/rfc9537.html#section-4.2) lets servers
describe removed or changed fields. This reader can accept those declarations only
when every declared path stays inside the root `entities` subtree. That subtree is
ignored by this checker. Redaction of the root, network bounds, identity, conformance,
notices or links stops the entire comparison. Unsupported expressions stop it too.
These are reader limits, not proof that the registry lacks geofeed support.

The reader parses a small subset of
[JSONPath](https://www.rfc-editor.org/rfc/rfc9535.html). It never runs expressions,
resolves matches, fetches linked data or changes the saved reply. The root must be
exactly `$.entities` or `$['entities']` (double quotes work too). Downward steps may
use ASCII member names, quoted keys, nonnegative indices, wildcards and slices with
nonnegative bounds and no step. Filters may compare a relative singular member/index
path with a quoted string, such as `$.entities[?(@.handle=='EXAMPLE-1')].vcardArray[1]`.
One pair of filter parentheses is optional. Quoted values remain literal data.
Unions, recursive steps, root references in filters, functions, logical operators,
escaped root aliases and unconsumed trailing expressions are refused.

`pathLang` must be `jsonpath`; its default is supported. The default method is
`removal`. This subset requires `prePath` for removal and `postPath` for `emptyValue`
or `partialValue`. `replacementValue` can use an in-place `postPath`. When it uses
`prePath`, this reader also requires `replacementPath`. If a replacement path is
declared, it must pass the same scope proof. A declaration cannot have both
`prePath` and `postPath`. Human names and reasons never decide which fields are safe.
The reply must declare `redacted` in `rdapConformance`.

Limits are 100 declarations per reply, 2,048 characters and 256 tokens per path,
256 characters per quoted token, 64 characters per unquoted member name and six
digits per index. Names and reasons use nonempty standard string fields, limited
to 1,024 single-line characters each. Empty or malformed metadata is refused.
Do not remove a declaration or change a path to force acceptance.

On 2026-11-18, offline classification of an unchanged saved public RIPE NCC reply
accepted all 12 entity-only declarations. Its original SHA-256 is
`c619e63c5d4992ba5cfa33b0c2657435f72f53580209c3c3d44528ff71e76003`.
The earlier reader had refused it. The original lookup time was not retained, so
a correctly dated CLI import of that reply remains unmeasured. No new lookup was
made for this follow-up. Classification does not establish full interoperability,
that a path matches data, or that a server applied redaction correctly.

Multiple geofeed links also stop the initial reader, including repeated URLs.
RFC 9877 allows language alternatives; choosing among them is not implemented here.
This is a reader limit, not invalidity of every response with several links.
Duplicate object versions, same-scope ambiguity and crossing scopes retain the
existing shared checks. No link or later file is silently dropped.

## Report and recovery

Single-file reports retain original and normalized hashes and label the source as
`operator_supplied_rdap`. Several-file reports retain each input's hashes, dates and
RDAP metadata. `rdap_redaction_status` is `not_present` or `ignored_entities_only`.
`rdap_ignored_entity_redactions` counts accepted declarations, not matched fields.
The multi-file summary totals that count as well as advertised, linked and
unknown-absence inputs. The oldest date describes the combined comparison. Original-file hashes stay
in `snapshot_inputs`; the top-level snapshot hash describes combined normalized data.
See [multi-file hash meanings](ripe-registry-input.md#more-than-one-response).

Reports omit raw contacts, handles, reference URLs and input paths. Dates are supplied
by the operator. Reads occur separately and do not form an atomic snapshot. No report
claims publication health. Bootstrap authority, ownership, signatures, current
allocation, public retrieval and provider ingestion remain unverified. Existing
`not_measured` fields still apply.

On refusal, keep feed, status and recovery files intact. Correct the saved input set
and rerun the read-only check. Return to the prior compatible version and its saved
RIPE or normalized input to undo this source change. No registry or hosting migration
is needed. Live lookup, language selection, signatures and further discovery work stay
open under [#70](https://github.com/MHammett/isp-geofeed-generator/issues/70).
