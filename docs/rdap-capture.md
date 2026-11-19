# Capture one RDAP network reply

`capture-rdap` makes one explicit, unauthenticated HTTPS GET to a supported RIR.
It uses the [saved-IANA planner](rdap-bootstrap-planning.md) to choose the endpoint
for the entire requested IPv4 or IPv6 prefix. Support is initial.

The command records the original response and its actual UTC completion time before
the strict RDAP reader parses it. It prints a small capture summary. It reads no
generator configuration or credential and changes no feed, publication status or
recovery file. It does not compare a feed, prove ownership or measure ingestion.

## One request, no handoff

The only destinations are the planner's five exact RIR HTTPS bases. There is no
arbitrary URL option, registry crawl, parent/child lookup, feed retrieval or automatic
bootstrap download. Environment proxies, authentication and cookies are not used.
TLS certificate and hostname validation remain enabled. Redirects and response links
are never followed. A redirect is saved and refused, even when it points to another
valid registry. This is an initial capture-profile limit, not a platform defect.

The request asks for `application/rdap+json` and identity encoding. A usable response
needs HTTP 200, that media type, no compressed encoding, a complete bounded body,
and a network covering the entire requested prefix. A larger containing object is
allowed; this does not prove that it is the most specific record in a full registry
hierarchy. The existing redaction, truncation, duplicate-key, unsafe-link and language
guards still apply. `--rdap-language` uses the same explicit exact-match rules as
[saved RDAP checks](rdap-registry-input.md). There is no language fallback.

The transport uses a 20-second socket timeout, an 8,000,000-byte saved-body limit,
and a 30-second elapsed budget checked between body reads and after the last read.
An in-progress socket read can overrun that elapsed budget by up to its socket
timeout. This is not a strict 30-second wall-clock deadline. There are no retries,
including after authentication failures, HTTP 429, timeouts or storage errors.
Use targeted reads sparingly. Follow the registry's access policy. Use approved bulk
data for large-scale work, as discussed in [RFC 9632](https://www.rfc-editor.org/rfc/rfc9632.html).

The query and HTTP contracts come from
[RFC 9082 section 3.1.1](https://www.rfc-editor.org/rfc/rfc9082.html#section-3.1.1) and
[RFC 7480](https://www.rfc-editor.org/rfc/rfc7480.html). Refusal limits above are this
tool's conservative profile; they do not describe every legal RDAP exchange.

## Restricted evidence folder

Choose an absolute **new** folder under an existing trusted parent. Keep capture
data outside the Git checkout. Raw public registry replies can contain contact data.
They must not be attached to a public issue or included in a discovery report.

On POSIX, the new directory has mode 0700 and files have mode 0600. On Windows, a
protected directory DACL grants full access only to the current process user and
SYSTEM. Files inherit that DACL. No existing folder or ACL is changed. These controls
do not protect against a compromised user, root or a privileged administrator.
Use the organization's normal protected storage and retention policy.

Fixed file names have these meanings:

| File | Meaning |
| --- | --- |
| `bootstrap.json` | Exact supplied bootstrap bytes, retained before the request |
| `request.json` | Planned endpoint, requested prefix, bootstrap dates/hash and intent time; written before the request |
| `response.body` | Original complete response bytes, including a complete error or refused reply |
| `response.partial` | Bounded incomplete bytes; never use these for comparison |
| `receipt.json` | HTTP status, byte count/hash, completion dates, media/encoding flags and read error; saved before parsing |
| `validation.json` | Separate accepted/refused reader result with a fixed reason code |

The immutable receipt says `validation: not_measured` because validation happens
later. Read `validation.json` for that later result. No raw headers, redirect targets,
contact values, local paths or returned geofeed URLs are printed in the summary.
Bootstrap origin, registry authority, ownership, allocation, signatures, public feed
retrieval and provider ingestion remain `not_measured`.

In Bash on Linux, replace the observation placeholder with the bootstrap's actual
download time, then choose a new folder:

```bash
isp-geofeed-generator capture-rdap --bootstrap-records /etc/isp-geofeed-generator/iana-ipv4.json --bootstrap-observed-at 'YYYY-MM-DDTHH:MM:SSZ' --rdap-prefix '11.22.33.0/24' --rdap-capture-dir /var/lib/isp-geofeed-generator/rdap-capture-001
```

In PowerShell on Windows:

```powershell
isp-geofeed-generator capture-rdap --bootstrap-records 'C:\ProgramData\ISP Geofeed Generator\iana-ipv6.json' --bootstrap-observed-at 'YYYY-MM-DDTHH:MM:SSZ' --rdap-prefix '2001:4860:1234::/48' --rdap-capture-dir 'C:\ProgramData\ISP Geofeed Generator\rdap-capture-001'
```

These example prefixes are syntax examples, not an ownership claim. Select the
operator's intended prefix. Static special-use addresses and noncanonical CIDRs
are refused before directory creation or network access. This diagnostic does not
refresh fullbogons or authorize a prefix for publication. Normal generation and
publication still require the current fullbogon and allocation guards.

## Use accepted evidence, investigate refusals

For accepted captures, pass `response.body` to `check-registry --registry-format rdap`
with the exact `response_observed_at` from the receipt. Use the normal local candidate
and exact public feed URL. [The comparison guide](registry-reference-checks.md)
explains its scope, dates and multi-file limits. It is a separate operation; capture
success does not mean the references match a feed.
The [capture-folder input](rdap-capture-input.md) is the simpler handoff: use
`--registry-format rdap-capture` and the folder path. It checks the saved evidence
and uses the exact receipt date automatically. Both routes accept up to six
fractional UTC second digits; the timestamp is not rounded to make it parse.

On refusal, stdout is empty and the command exits with failure. Inspect the saved
receipt and validation code privately. Original bytes are retained even when the
reader refuses them. A crash or storage failure can leave an incomplete folder.
The command never resumes, overwrites or deletes it. The same destination stops
before another request. Do not bypass a refusal by editing a response or supplying
a made-up date. Investigate read-only first; a new explicit capture needs its own
new folder. No publication rollback is needed because this command never publishes.

Keep this outside scheduled publication until operator testing. Contributions and
sanitized fixtures are welcome. Referral support and bulk access need separate
contracts and tests; they are not silently enabled by this command.
