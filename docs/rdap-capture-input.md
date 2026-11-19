# Compare a candidate with saved RDAP captures

`check-registry --registry-format rdap-capture` reads one or more complete
[capture-rdap](rdap-capture.md) folders. It uses each receipt's original observation
date and recorded language. No date needs to be copied from a separate report.
Support is initial. Contributions and sanitized fixtures are welcome.

This operation is offline. It does not contact a registry, fetch a link, read tool
configuration or credentials, publish, or write status and recovery files. Generate
and validate the candidate through the normal ownership and current fullbogon checks
first. A comparison does not authorize publication or prove provider ingestion.

## Run the comparison

Choose complete capture folders with `validation.json` marked accepted. Keep them
outside the checkout because original replies can contain contact data. In Bash:

```bash
isp-geofeed-generator check-registry --registry-format rdap-capture --registry-records /var/lib/isp-geofeed-generator/rdap-capture-001 --registry-records /var/lib/isp-geofeed-generator/rdap-capture-002 --feed /var/lib/isp-geofeed-generator/candidate.csv --feed-url 'https://example.net/geofeed.csv'
```

In PowerShell on Windows:

```powershell
isp-geofeed-generator check-registry --registry-format rdap-capture --registry-records 'C:\ProgramData\ISP Geofeed Generator\rdap-capture-001' --feed 'C:\ProgramData\ISP Geofeed Generator\candidate.csv' --feed-url 'https://example.net/geofeed.csv'
```

Use the real candidate path and exact stable public feed URL. Neither the feed URL
nor any returned URL is fetched. `--config` is accepted but not read. Do not add
`--registry-observed-at` or `--rdap-language`: overrides are refused before reading
the captures. For a separate explicit language choice or independently saved reply,
use the ordinary [raw RDAP input](rdap-registry-input.md) and its actual date.

Repeat `--registry-records` for up to 32 capture folders. The command uses one selected
format for the whole set; mixed raw files and folders are not supported. For a nested
candidate that was explicitly generated with that policy, add
`--reference-policy longest_prefix`. This configures only the diagnostic.

## What is checked

Only these fixed members are read: `bootstrap.json`, `request.json`, `response.body`,
`receipt.json` and `validation.json`. No path in the JSON is followed. Directory
symlinks/reparse points, non-directory inputs, missing members, unsafe file types
and a `response.partial` entry are refused. Extra unrelated files are not imported.

The version-1 receipt must describe a complete HTTP 200 response, supported media
and encoding, no read error, and the expected fixed body name. Its byte count and
SHA-256 must match the original body. The accepted validation flag is required but
never replaces parsing: the strict RDAP reader runs again, including redaction,
truncation, unsafe-link and recorded-language checks.

The saved bootstrap is replanned using the recorded plan time and requested prefix.
The resulting plan must match the saved one, including the supported RIR endpoint
and bootstrap hash. UTC dates must be valid, ordered and not in the future. The
request's returned network must cover the whole query. Members are read again before
use to refuse changes during a bundle read. This is a local consistency check, not
a lock or an atomic snapshot across multiple independently collected folders.

Every member's bytes count toward the existing 8,000,000-byte combined input limit.
This includes the bootstrap and metadata, not just response bodies. Per-member limits
are 1,000,000 bytes for bootstrap data, 32,000 for request metadata, 8,000 for the
receipt and 1,000 for validation. A capture at the writer's maximum body size can
therefore exceed the comparison's combined budget. Do not trim originals to force
acceptance. Use a smaller explicit set or a separately reviewed workflow. The normal
object, duplicate-ID, crossing-scope, feed-size and exact-reference rules still apply.

## Read the result correctly

Each input reports its original body hash, all-member manifest hash, consumed bytes,
exact receipt date and recorded language. Fractional UTC seconds are preserved. The
combined date is the oldest receipt, including fractional seconds. Date provenance
is `capture_receipt_unverified`; no file modification time is used.

`capture_integrity: internally_consistent` means the supplied files agree with one
another and passed the supported readers. **The files are editable. A fully rewritten,
internally consistent bundle can still pass.** Hashes are not signatures and do not
prove an actual HTTP event, an unmodified original capture, most-specific registry
authority or address ownership. `capture_authenticity`, `registry_authority` and
`bootstrap_authenticity` remain `not_measured`.

The ordinary comparison result keeps reference coverage and feed consistency
separate from public retrieval, allocation, signatures and ingestion. An absent link
still retains the reader's distinction between advertised support without a returned
link and unknown availability. A green local comparison is not proof of ingestion.

## Refusal and recovery

One refused or changed folder stops the whole set. There is no partial JSON report,
deduplication, replacement with a newer version or silent omission of a later input.
The checker changes no files, so no publication rollback is needed.

Inspect the originals and receipt privately. Keep refused evidence. Do not make a
capture appear accepted by editing flags, dates or hashes. Use an intentional new
capture when a fresh network observation is needed. That is a separate command and
request, not an automatic retry. Never attach raw contact payloads to a public issue.
