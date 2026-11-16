# BillMax: initial AP-network support

This adapter reads selected access-point networks from BillMax Core API v1. It follows
the AP's native expanded POP association. It does not infer a join from AP or POP names,
read subscriber IPs or use assets to invent a containing pool. Contributions and sanitized
operator feedback are welcome. No live BillMax instance has been tested.

## Public contract checked

Checked on 2026-11-16 from the vendor's [API reference](https://billmax.com/api-reference/),
its linked [Core Swagger UI](https://demo5debian.billmax.com:3105/api/billmaxCoreApi/v1/api-docs/)
and [authentication guide](https://www.billmax.com/billmax/webhelp/REST.html).
The UI embeds OpenAPI 3.0.1 with API version `v1.0.0` in `swagger-ui-init.js`.
The reviewed document contains 136 paths. Documentation was downloaded; no demo data
endpoint, login or mutation was called.

- `GET /aps` documents field selection, offset/row-count limits and ordering.
- `GET /aps/{id}?pop=true` returns an array with one `apext` record, including its
  `networkMask` and `_pop` array. That expansion supplies native POP IDs and geography.
- The AP mask pattern documents IPv4 `/16` and `/24`. The adapter accepts only those
  canonical CIDRs. It refuses single addresses, host bits, other masks and IPv6.
- POP geography includes `country`, `stateProvince` and `city`. Examples use display
  values such as `USA` and `Texas`, so valid ISO output is not assumed.

The general `/pops` collection response points to an asset schema in the reviewed
document. This adapter avoids that inconsistent collection contract. Its POP data comes
from the explicitly documented AP detail expansion. No full vendor schema or vendor
implementation code is bundled.

## Configure the instance and selection

Maintain the AP's network/netmask and its POP assignment in BillMax. Check that the
**whole selected subnet** belongs at that POP. Generated or assigned individual IP assets
are a separate inventory. An AP network may contain unused addresses; this adapter does
not claim to export only assigned addresses or to reproduce every pool in BillMax.

The schema does not establish whether `networkMask` is customer-serving space or an
AP management network. Confirm its purpose on your instance before selecting the AP.
A valid public CIDR and a native POP link do not prove that it belongs in the customer
geofeed. Leave management-only networks out unless your publication policy deliberately
includes them at that location. Do not infer customer pool coverage from the field name.

Start with [the example](../config.billmax.yaml.example). Set `BILLMAX_URL` to your full
HTTPS Core v1 base, including its deployment port and path, for example
`https://billing.example.net:3105/api/billmaxCoreApi/v1`. The adapter appends operations
to that base. HTTP, credential-bearing URLs, query strings and fragments are refused.
For a [named input](multiple-inputs.md), use that input's `url` and explicit credential
references instead of environment URL fallback.

With no `source.ap_ids`, discovery reads an AP directory. It requests only ID, name,
mask, POP display value and status. It stops at an empty page, even if the server returns
fewer rows than requested. Invalid, repeated or unordered IDs stop discovery. The
directory has no documented total count or snapshot token, so concurrent edits could
affect an offset-based listing. Compare it with the instance before selecting IDs.

Set `source.ap_ids` to reviewed positive digit-string IDs, at most 10,000. Discovery
then reads only those details and their POP expansions. Publication requires this
explicit selection and does not depend on a paged directory. Every selected ID must
return exactly one matching AP and one POP with a stable positive ID. Missing records,
inaccessible records, invalid masks and conflicting coarse geography stop the whole run.
Requests set `active=true` and disable notes and tickets.

The snapshot uses `ap:<id>` for prefixes and `pop:<id>` for sites. Structured POP values
are used as supplied; the adapter does not translate display names or automatically add
a country to a short state code. Use reviewed `site_locations`, keyed by `pop:<id>`,
when needed. For example, map to `country: US` and `region: US-TX` after checking the
actual POP. Missing native POP expansion is an instance/API evidence problem and stops
the read before a private map can hide it. Street addresses, postal codes, coordinates,
notes and unrelated response fields are discarded from the normalized snapshot.

## Authentication and permissions

Use [secure credential-store references](security.md). Every mode needs
`BILLMAX_API_KEY`, sent only in the `api_key` HTTPS header.

- `source.auth_mode: api_key` matches the vendor's `USER_AUTH=NONE` mode. It means the
  deployment requires the API key alone; it does not mean unauthenticated access.
- `source.auth_mode: userpass` matches `USER_AUTH=USERPASS`. Supply secure
  `BILLMAX_USERNAME` and `BILLMAX_PASSWORD` references too. The adapter performs one
  documented `POST /login`, then uses its `BXSESSIONID` as a Bearer token for reads.
  The returned session token stays in memory and is never added to discovery or status.

Use the deployment's existing auth mode. Do not disable user authentication for this
adapter. Ask the platform administrator for a dedicated reader with AP and linked POP
access; exact job-class permission settings need verification on that version. Do not
grant customer, payment, asset-change or provisioning-write permissions. The adapter
does not call any data-changing endpoint. Login is the only POST in userpass mode.
Authentication failures and timeouts stop without retry or fallback. A refused session
requires operator diagnosis, not automatic credential reset.

The platform may return complete AP/POP objects because their detail endpoint does not
document field selection. Notes and tickets are explicitly disabled and extra fields are
discarded. Restrict access to discovery exports, which still contain private inventory.

## Verification, limits and recovery

Schema-based fixtures check exact `/16` and `/24` coverage, native links, private-field
discarding, both auth modes, named-input credentials, clamped directory pages and failure
cases. An installed wheel generates a feed from a selected AP outside the checkout.
CLI tests prove initial-support opt-in, successful publication and retained feed/backup
bytes after a broken link or a failed second selected AP. These are synthetic workloads,
not live BillMax verification.

Before scheduling, compare AP/POP IDs and whole-subnet coverage with the instance,
generate a candidate and verify geography and ownership. Test publication and recovery
on staging. Set `source.allow_initial: true` only after those checks. All normal ISO,
ownership, no-bogon, overlap, withdrawal and location-change controls still apply.
Multiple selected APs sharing one subnet are rejected as duplicate coverage, not merged.
Keep the existing timer stopped while diagnosing a source failure. Correct the source or
mapping, generate again, verify and then resume. No failed source read changes the feed.

BillMax's general pool exports, asset-to-pool completeness, other IPv4 masks and IPv6
remain unverified adapter work. This is not a claim that BillMax lacks those features.
Creators: please document these reads, stable joins, permissions and pagination, and
correct the collection schema reference. Operators can help by supplying sanitized
version-specific shapes. Keep [issue #11](https://github.com/MHammett/isp-geofeed-generator/issues/11)
open for those broader contracts and independent operator tests.
