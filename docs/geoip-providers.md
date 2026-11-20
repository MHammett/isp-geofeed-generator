# GeoIP providers and registration workflows

Public documentation checked on 2026-11-16. This is research and an implementation plan
for [issue #24](https://github.com/MHammett/isp-geofeed-generator/issues/24).
It does not add a provider adapter or submit data. No account was created, form sent,
registry changed or provider key used. Contributions with current vendor docs and
sanitized operator test results are welcome.

## Four separate jobs

1. **Host the feed.** Publish validated CSV at a stable public HTTPS URL. The existing
   WordPress target checks stored and public bytes. File output checks local bytes;
   operators must also check the public route before enabling a timer.
2. **Register the URL.** Tell a provider where to fetch it. This may be a one-time form,
   portal action or documented API. Registration is not evidence of later ingestion.
3. **Submit corrections.** Send records or a file to one provider. A receipt is not
   evidence that the provider accepted the location or applied it to a database.
4. **Publish discovery metadata.** Add a reference to the address registry record.
   This helps consumers find the feed. It does not update their databases directly.

One feed can serve many providers. Do not create a new source adapter for each provider.
Keep registration and submission separate from the guarded feed publishing contract.

## Provider evidence

The [Brothers WISP directory](https://thebrotherswisp.com/geo-and-vpn) was the starting
point. The [RIPE provider directory](https://docs.db.ripe.net/Related-Software-and-Tools/Geolocation-in-the-RIPE-Database),
provider guides and their linked correction pages widened the search. Those directories
are leads, not API specifications. The rows below use provider-owned sources.

**Unknown** means the reviewed public pages do not establish the detail. It does not mean
the service lacks that feature. Lookup APIs and database-download APIs do not establish
a correction-write API. Listed lookup prices do not establish a submission charge.
No provider's live acceptance, control check or update time was measured here.

| Provider | Documented workflow and data | Account, control, limits and adapter decision |
| --- | --- | --- |
| [MaxMind](https://www.maxmind.com/en/geoip-data-correction-request) | Network operators can use [GeoIP Exchange](https://www.maxmind.com/en/geoip-exchange) or correction forms; geofeeds are supported. | Account/portal enrollment applies to Exchange. Correction forms offer account or email verification. [Developer docs](https://dev.maxmind.com/geoip/geoip-exchange/) specify authenticated report **downloads**, not geofeed writes. Submission charges, write limits, cancellation and an automated write contract remain unknown. Keep enrollment manual. |
| [IPinfo](https://ipinfo.io/corrections) | Public correction entry point. Its [accuracy guide](https://ipinfo.io/blog/verifying-ip-address-accuracy) describes geofeeds and corrections as evidence checked against its measurements. | The correction page's form details were not exposed in the retrieved text. Current submission auth, control checks, limits, fees and withdrawal contract are unknown. Do not infer a write API from its lookup API or promise adoption of a feed. |
| [DB-IP](https://db-ip.com/faq.php) | FAQ recommends published geofeeds, per-IP reports and batch updates through its contact form. | Public FAQ does not specify a correction API, registration auth, proof-of-control process, batch limits, fees or withdrawal semantics. It still links an old feed draft. Use the current project CSV policy and confirm provider requirements manually. |
| [IP2Location](https://blog.ip2location.com/knowledge-base/what-is-geofeed/) | Discovers feed links in network WHOIS. Requires prefix, country, region and city; postal may be empty. Inclusion is reviewed and may be revoked. | A valid project CSV with an empty region is not sufficient for this provider's stated policy. Do not invent a region. Auth, fees, size limits, withdrawal and a write API are not specified by this guide. Confirm the exact enrollment route. |
| [IPLocate](https://www.iplocate.io/corrections) | Prefers a public geofeed URL; also offers form/email corrections. Its [guide](https://www.iplocate.io/blog/geofeeds) describes registry discovery and recurrent fetches. | The form asks for work email to help verify the sender. It also displays a browser-location permission requirement; it was not submitted. Size limits, fees, withdrawal and correction API are unknown. Browser location is not a requirement of this tool. |
| [Ipregistry](https://ipregistry.co/data-corrections) | Recommends a geofeed for network owners and links a correction contact. Its [feed guide](https://ipregistry.co/blog/geofeeds) describes recurring consumption and provider-side validation. | Acceptance is not guaranteed. No submission API, auth contract, size limit, fee or withdrawal behavior was established. Manual correction contact is not an API. Provider normalization may differ from the published place name. |
| [IPHub](https://iphub.info/isp-tools/create-or-submit-geofeed) | Offers public-URL submission and hosted-feed creation/management. The [URL form](https://iphub.info/isp-tools/submit-geofeed) requires a public CSV URL and contact email. | Login or registration associates a feed with an organization. Ownership checks, API auth, size limits, charges and withdrawal behavior are unknown. Hosting and URL registration are separate choices. No form automation is planned. |
| [ipgeolocation.io](https://ipgeolocation.io/corrections.html) | Correction page recommends sharing a geofeed URL and offers individual and bulk correction forms. Its [guide](https://blogs.ipgeolocation.io/blogs-site/how-to-set-up-a-geofeed/) covers hosting and registry pointers. | Form asks for contact/company details. A public correction API, proof-of-control contract, size limits, charges and withdrawal behavior were not established. Its lookup API is a separate product. |
| [IPFire Location](https://www.ipfire.org/location/report-a-problem) | Documents reporting a database problem through Bugzilla with supporting information. | An IPFire account is required for the ticket. This is a manual report workflow, not a documented feed registration or write API. Feed formats, ingestion limits, control checks, charges and withdrawal are unknown. Do not confuse Location with its domain blocklist. |
| [ipapi.is](https://ipapi.is/corrections-via-api.html) | Documents JSON POST corrections, with a feed URL or feed rows. Account API key goes in the JSON body. A successful message means receipt. | This is positive evidence of an automated submission capability. Docs describe input checks and HTTP 400 errors, but no idempotency key, applied-state read-back, cancellation or feed-replacement/withdrawal contract. Size/rate limits and correction charges are unknown. Clarify the documented prefix-length bound before implementing it. Candidate for a separate initial **submission** adapter, not a verified publishing target. |
| [ipdata](https://ipdata.co/corrections.html) | Requests geofeeds from network owners/operators by email and says it does not make individual-IP corrections. | Manual contact. Auth/control steps, limits, fees, withdrawals and correction API were not established. Keep this separate from paid lookup API access. |
| [BigDataCloud](https://www.bigdatacloud.com/update-my-location) | Network operators are directed to publish a geofeed or work with the provider. Individual-device location sharing is a separate path. | Reviewed page does not define a submission API, account/control contract, feed limits, fees or withdrawal rules. Do not collect operator GPS data to locate entire pools. |

Do not treat provider lookup responses containing `XK` or `ZZ` as permission to publish
those country codes here. The generator's assigned-ISO and no-bogon policy still applies.
An IP2Location-specific submission must fail clearly when required region data is absent.
CSV is the coarse country/region/city profile. Latitude/longitude or another richer profile
requires a documented destination contract and an explicit field selection; never append
extra columns to the shared CSV to satisfy one provider.

## Registry discovery

The [Geoflaw workflow](geoflaw.md) adds a manual check for reference, retrieval and
coverage findings. Keep its dataset dates and reported findings separate from current
local checks and actual provider ingestion. Implementation is tracked in issue #70.

[RFC 9632](https://www.rfc-editor.org/rfc/rfc9632.html) describes RPSL registry references,
including coordination with the RIR/NIR/LIR responsible for the address records. The
registry reference must cover the address space being claimed. One organization's postal
address does not locate all its routed space. Optional RPKI feed signing is a separate
proof mechanism; this project does not generate or verify such signatures yet.

[RFC 9877](https://www.rfc-editor.org/rfc/rfc9877.html), published in October 2025, adds
RDAP geofeed links and the `geofeed1` extension identifier. It registers
`application/geofeed+csv`. That standard defines discovery responses, not a universal
registry-write endpoint. Check each registry's current deployment and authenticated edit
procedure. The project's existing HTTP media types are unchanged by this research.

[LACNIC's service description](https://www.lacnic.net/4682/3/lacnic/geofeeds--os-servicos-do-lacnic-incorporam-nova-ferramenta)
also describes location entry by administrators in MiLACNIC and public combined data.
That is an additional hosting/data-entry workflow. It is not proof of an API that can
register an arbitrary external URL. Current eligibility and write contracts need separate
checks. No claim is made that every RIR deploys the same fields or RDAP extension.

## Safe implementation plan

The existing version-1 target SDK promises checked publication and recovery. Do not
return a provider receipt as a healthy `Target.publish()` result. Add a separate,
versioned registration/submission interface before enabling these operations. Keep trusted
extensions in separately installed packages, as in [local customization](customization.md).

The interface must carry these facts separately:

- Destination ID and operation: host, register URL, submit records or check status.
- Exact validated payload SHA-256, format/profile and public URL where relevant.
- Outcome: not attempted, manually required, rejected, receipt received, unknown after
  timeout, or applied as independently observed. Omit unsupported claims.
- Provider receipt ID if documented; safe error code; check time from a clock.
- Verification scope. Sampling lookups cannot prove an entire prefix was applied.
- Recovery/withdrawal capability and the baseline used by local change guards.

Do not store API keys in payload artifacts, URL query strings, receipts or logs.
Use supported secret-store references and redact both request and response errors.
Send keys only to the fixed documented HTTPS endpoint; never forward them on redirects.
Bound requests, responses and timeouts. A provider-controlled URL is not permission to
fetch local, link-local, private or arbitrary credential-bearing resources.

Registration must first verify the approved public URL serves the exact validated bytes.
When an API fetches the URL later, record the local hash and the fact that its fetched
version is unmeasured unless the provider supplies evidence. Keep a changed URL or feed
from silently changing a pending submission's identity.

For multi-destination work, validate once and record a result per destination. Never
report total success after a partial failure. Keep a successful host publication when a
registration fails; do not undo unrelated destinations. An unknown submission result
must stop automatic retries unless the provider documents idempotency or a status lookup
resolves it. HTTP method alone does not prove retry safety. A new payload needs a new
reviewed operation. Removing a row is not assumed to retract a prior correction.

Before an initial adapter is enabled, fixtures must force bad credentials, rejected data,
oversize bodies, redirects, timeouts before/after receipt, ambiguous success, changed
public bytes, duplicate attempts and partial multi-destination failure. Prove receipts
cannot be mislabeled as applied state. Keep initial support labels until other operators
test the workflow. Production submissions need specific operator authorization.

## Questions for platform creators

Please publish stable correction and registration APIs with read-back, ownership checks,
documented limits, idempotency, replacement/withdrawal behavior and a test environment.
Make country/region/city and coordinate profiles explicit. Return a receipt that can be
checked later, and distinguish received, accepted and applied. These are requests to
platform creators; operators should not have to guess undocumented API joins or states.

For billing and IPAM creators, expose exact pool/subnet boundaries, stable IDs and native
links to sites with structured coarse geography. State permissions, pagination and IPv6
behavior. A missing assignment is an instance setup problem; an undocumented join is an
API evidence gap; missing adapter coverage is this project's work. Keep those separate.
