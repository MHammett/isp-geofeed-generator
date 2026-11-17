# Verification

## Real packet-limit refusal and deliberate correction

Observed on 2026-11-17 from [hosted run 44159141685](https://github.com/MHammett/isp-geofeed-generator/actions/runs/44159141685)
at `936a3d1`. All eight jobs passed, including five Python jobs running 353 tests.
Four real WordPress cases covered both APIs and three-byte/four-byte Unicode feeds.
Each failed PUT measured an 8,388,608-byte database session budget and received the
origin plugin's HTTP 503 `geofeed_db` response. Prepared statements ranged from
8,584,900 to 12,837,412 bytes. The full stored document and public baseline stayed exact,
private recovery data remained usable, and the failed runner status stayed unhealthy.

After restoring and measuring the saved 16,777,216-byte budget, an explicit new run
of the same CSV and same-sized statement passed in every case. Stored current/prior
bytes, public CSV and private recovery history were verified. Each phase had one
runner PUT and one query-filter call. Raw driver attempts remain not measured because
WordPress can replay a query internally. The fixture restores the saved limit in
`finally`, and a local guard probe refused both entry points outside the disposable
environment with zero subprocess calls.

The prior capacity, race, HTTPS, policy, cache/delivery, range, credential and external
validator workloads also passed. No production setting, plugin or publisher changed.
See [the measured packet workload](wordpress-integration.md#measured-packet-refusal-and-correction).
Finite memory and managed-host/CDN behavior remain unmeasured.

## Nested policy publication and review follow-up

Observed on 2026-11-16 at 20:53:15 UTC from hosted run
[43952432969](https://github.com/MHammett/isp-geofeed-generator/actions/runs/43952432969)
at `c0ecc5c`. All eight jobs passed. Each of the five Python jobs ran 306 tests;
Windows skipped two POSIX-only checks. Each of the four Linux Python jobs also passed
89 legacy and 37 policy-v2 PHP checks. Installed-wheel workloads exercised nested
multi-input publication, unchanged local policy/history and conditional recovery on
Linux and Windows. Both pinned external validators accepted both versioned CSV cases.

Real disposable WordPress trials covered separate administrator setup, publisher
refusal, policy/feed races, parent-fallback refusal, lost replies, failed recovery,
other-writer preservation, empty/strict baseline restoration and approved strict
migration. Read-only inspection preserved the failed publication status after recovery.

The administrator HTTPS mutation recorded two core-authenticated HTTP administrator
requests: the intact guard refused, while the removed guard committed a policy change
with HTTP 200. Restoring the guard again refused HTTP and allowed HTTPS. The earlier
publisher HTTPS and unsafe SQL mutation controls also passed.

Claude's reviews of #67, #68 and #69 cover their earlier heads. Their independent
guard oracle and crash probes are recorded in [review scope](review-followup.md),
separately from this author's WordPress workload. This later protocol has not yet had
an independent review or a managed-host staging test. A local Windows fault-test run
also encountered `PermissionError` at a private backup replacement; its cause was not
established. It stopped before publication. Hosted Windows passed the full suite; that
does not establish the local machine's cause. No runtime retry was added.

No production plugin, credentials, feed, timer or registry record was changed.

## Plugin HTTPS guard after core authentication

Observed on 2026-11-16 from hosted run
[43928343797](https://github.com/MHammett/isp-geofeed-generator/actions/runs/43928343797)
at `370260d`. All eight jobs passed. This author workload addresses the coverage gap
in [Claude's review of #62](https://github.com/MHammett/isp-geofeed-generator/pull/62#pullrequestreview-5925077906).

A private, temporary fixture setting let core verify real application passwords on
loopback HTTP. The hook recorded a core-authenticated publisher before the plugin's
HTTP 403, and the stored document and geofeed write log stayed unchanged. Removing only
the plugin's HTTPS condition in the private copy produced HTTP 200 and committed the
candidate with the correct prior feed. The refusal check detected that unsafe outcome.
Restoring the original plugin again refused HTTP without writes and allowed HTTPS.
The mutation and core transport exception were removed in `finally`.

This is a measured disposable-stack control, not a change to the shipped authentication
or a production proxy measurement. The prior race, recovery and large-Unicode workloads
also passed. The review and this author follow-up remain separate evidence.

## Populated-history WordPress capacity and recovery

Observed on 2026-11-17 from [hosted run 44138616802](https://github.com/MHammett/isp-geofeed-generator/actions/runs/44138616802)
at `fd18752`. All eight jobs passed. Each of five Python jobs ran 342 tests;
platform-specific checks were skipped only on the other platform. The real WordPress
job completed four capacity cases: API v1 and v2, each with three-byte and four-byte
Unicode city characters.

Each case published first and changed three times with populated history. Later
normal updates reached 8,583,154 or 12,832,174 SQL bytes for roughly 981 KB of CSV.
Each unchanged run made zero HTTP writes and zero geofeed SQL writes, preserving
private recovery bytes and modification times. A forced public mismatch then caused
one publish and one conditional restore, with exact stored/public recovery and an
unhealthy result. Policy-v2 recovery also preserved all three policy fields.

The prior small-client and oversized-CSV refusal controls passed, as did the existing
race mutations, HTTPS controls, policy and delivery tests. The first attempt at the new
workload failed because its assertion expected v1's recovery message from v2. The test
was corrected to check each protocol's actual message; runtime code was unchanged.

See [all measured stages and limits](wordpress-integration.md#measured-populated-history-workloads).
Actual packet-limit failures, finite host memory and the managed-host/CDN path remain
unmeasured. No production setting changed.

## Near-limit WordPress Unicode workload

Observed on 2026-11-16 from hosted run
[43926425105](https://github.com/MHammett/isp-geofeed-generator/actions/runs/43926425105)
at `a8e20d0`. All eight jobs passed. The real WordPress/database workload published
and changed a 4,735-record feed, then kept its stored document and recovery files
unchanged on a repeat run with zero geofeed SQL write attempts.

The CSV was 980,230 bytes. Measured upload JSON was 1,842,098 bytes, state JSON
3,693,183 bytes and the largest SQL statement 6,434,412 bytes. The test database
packet budget was 16,777,216 bytes; HTTP PHP reported `post_max_size=8M` and
unlimited test-runner memory. These values measure this input, not a universal bound.

A client capped at the former 2,000,000-byte state budget failed at its size guard
without writes. An oversized CSV received HTTP 400 and preserved stored and public
bytes. The normal client passed the same large state workload. See the
[integration guide](wordpress-integration.md#measured-large-feed-example) for scope.
Production-host capacity, finite-memory behavior and CDN limits remain unmeasured.

## Real WordPress/database integration

Observed on 2026-11-16 from hosted run
[43924616247](https://github.com/MHammett/isp-geofeed-generator/actions/runs/43924616247)
at `710d93a`. All eight jobs passed. The new workload ran official hash-pinned
WordPress 7.1.4 with PHP 8.3.6 and MariaDB 10.11.14 on a disposable Ubuntu 24.04 runner.
This is a measured local test stack, not a production-host or CDN measurement.

Real application-password/role checks passed, including denied anonymous, subscriber,
incorrect-password and forged-forwarding HTTP writes. The installed generator CLI
published first and changed feeds, verified exact unauthenticated CSV bytes/headers,
and performed an unchanged run without geofeed SQL writes or recovery-history changes.
Invalid ISO, duplicate and bogon payloads kept the stored feed intact.

Two actual PHP workers reached each pre-write barrier. The first-insert negative control
executed `REPLACE` twice and exposed a losing request overwriting the winner; the normal
insert preserved one winner. The case-only update control held history constant on a
case-insensitive column: without binary comparison both writes succeeded, while the
normal comparison preserved one winner. The tests first refused to claim a negative
control when HTTP workers were still executing cached original code. HTTP cache settings
and observed SQL verbs are now explicit preconditions.

Stale public preflight stopped before writes and preserved local history. Bad read-back
and a lost successful reply both led to verified conditional recovery. A concurrent
authenticated winner was left intact. Refused recovery kept candidate bytes, old private
backups and unhealthy status, with no false restored claim. Every forced fault was observed.

Local checks also refused a changed core archive before extraction and refused unsupported
Windows/non-disposable execution before application imports. Windows did not run the real
stack. [The workload guide](wordpress-integration.md) records scope, isolation and limits.

## Adapter review follow-up

Observed on 2026-11-16 (America/Chicago). Windows ran 254 tests: 252 passed and two
POSIX-only skips. The new NIOS regression uses IPv4 and IPv6 references ending in
`Company%201` while the returned view name is `Company 1`. Exact references survive
selection and the feed retains 256 IPv4 addresses and four IPv6 addresses. Negative
controls refuse decoded raw-space references in configuration and returned inventory.
This verifies synthetic behavior; a spaced view on a live grid remains unmeasured.

The cached vendor BillMax schema has no purpose description on `networkMask`. The
setup guide and example now explicitly call for checking whether it is customer-serving
or management-only before selection. Claude Code's four later reviews are linked in
the [review record](review-followup.md), with their source checks and live-test limits.
Runtime code is unchanged; no source tenant, grid or production feed was changed.

## Infoblox NIOS networks

Observed on 2026-11-16 (America/Chicago). Windows ran 253 tests: 251 passed and two
POSIX-only skips. Thirteen new synthetic NIOS tests cover exact IPv4/IPv6 coverage,
declared/inherited attribute values, opaque references, distinct views, credential
scope, paging and failure controls. A foreign-looking continuation token stays encoded
as data on the configured endpoint. Duplicate references, repeated/invalid tokens,
empty intermediate pages, malformed results, wrong-family boundaries and inventory
budget exhaustion stop the read. Oversize declared values are discarded as invalid.

CLI controls first refuse publication without initial-support opt-in, then publish and
force malformed attributes or a missing selected network. Both failures leave the feed
and backup bytes intact and record unhealthy status. An isolated installed wheel builds
the exact IPv6 feed outside the checkout, alongside the existing BillMax, NetBox,
multi-input, approval and unchanged-output workloads. No live NIOS access or behavior
was measured. See [NIOS setup and recovery](infoblox-nios.md).

## BillMax selected AP networks

Observed on 2026-11-16 (America/Chicago). Windows ran 240 tests: 238 passed and two
POSIX-only skips. Twelve new synthetic tests cover exact IPv4 /16 and /24 AP networks,
native expanded POP IDs, both documented auth modes, private-field discarding, ISO
overrides, named-input credentials and directory pagination with clamped pages.
Forced invalid/missing details, bad native links, changed POP geography, unsupported
boundaries, authentication failures and timeouts all stop the source read. CLI controls
prove that initial publication needs opt-in, then publish successfully and retain feed
and backup bytes when a link breaks or a second selected AP is missing. Failure status
is unhealthy, separate from a successful read.

An isolated installed wheel built a feed from an AP and its native POP outside the
checkout, then passed the existing multi-input, location-approval and unchanged-output
workloads. The public Core v1.0.0 schema supplies the response shapes. Its /pops
collection inconsistency is avoided through AP detail expansion. This is initial narrow
support; no live BillMax tenant, general pool completeness or IPv6 behavior was measured.
See [BillMax setup and recovery](billmax.md).

## Operator review notes

Observed on 2026-11-16 (America/Chicago). Windows ran 228 tests: 226 passed and two
POSIX-only skips. The new diagnostic control first failed on raw IPv6 counts. It now
checks 50% coverage, a tiny nonzero move and one address above a 50% threshold. Messages
show readable percentages and note display rounding; exact integer comparisons still
stop a one-address excess. Existing guard and approval workloads remain in the suite.
The ISO control also explicitly refuses `XK`. The review guide links independent evidence
and records unreviewed lock/live/publication/license areas instead of treating agreement
or general CI passes as full review.

## Alternate NetBox geography models

Observed on 2026-11-16 (America/Chicago). Windows ran 227 tests: 225 passed and two
POSIX-only skips. Fifteen new tests cover prefix custom fields, GeoBox choice/enable
fields, complete Region hierarchies, missing/cyclic/deep/conflicting scopes, private
error context, same-VRF range parents and no fallback to broader prefix geography.
Both modes also emit an exact five-address IPv6 range without expanding to its parent.

The first twelve controls failed against the old site-only implementation, which requested
the Sites endpoint or rejected the new CLI settings. Current CLI workloads publish both
models, then lose required data and prove unhealthy status with unchanged feed and backup
bytes. Existing site/location and multi-input tests remain in the full suite. Installed
wheels also build both modes outside the checkout.

Vendor Prefix/Region docs and pinned prior-art setup/field schemas establish the models.
No unlicensed implementation was copied. No live alternate-model NetBox read or publication
was run. See [the model guide](netbox-location-models.md) for selection, permissions,
authority, strict completeness and migration/recovery behavior.

## ISO membership and independent conformance

Observed on 2026-11-16 (America/Chicago). Windows ran 212 tests: 210 passed and two
POSIX-only skips. New controls first reproduced accepted unassigned countries and
nonexistent subdivisions. The same controls now fail before publication. Rich JSON also
checks selected country/region fields, while coordinate-only output remains independent.
Direct CSV, WordPress and rich-JSON output controls retain prior feed and backup bytes
for invalid codes, even with relocation approval permitted. This control failed against
the previous publisher before the membership change.
Missing/changed ISO data is refused, and Python/plugin data and notice files match exactly.

Installed core and external adapter wheels passed outside the checkout, including data
hash checks, all notices and the existing guarded/unchanged publication workload. The
deployment plan includes all ISO files. PHP uses the same conformance fixtures, and its
separate process workload checks absent, changed and intact data installations.

Pinned Candela and MaxMind tools ran on 13 local synthetic controls. Both reported invalid
prefixes; only Candela reported the invalid ISO-country/subdivision controls in this mode.
Neither reported duplicate/nested prefixes in the experiment. Their lack of an error is
not a broader health or geography claim. Full results and the licensing/recovery policy
are described in [conformance](conformance.md). Hosted logs are recorded on the PR after
upload. Live source inventory, WordPress publication and real geography remain unmeasured.

## Safe source record diagnostics

Observed on 2026-11-16 (America/Chicago). Windows ran 203 tests: 201 passed and two
POSIX-only checks skipped. Fourteen new tests cover Sonar DHCP/inline management fields,
site addresses, IP-assignment owners, nested controller relations and discovery inventory;
Splynx IPv4/IPv6 fields and ranges; phpIPAM subnet/location fields; malformed/duplicate IDs;
and full CLI failure workloads for all three sources.

The initial twelve tests reproduced missing context, raw parse exceptions or accepted bad
IDs against the prior implementation. A further nested-discovery control was run against
the untouched previous worktree: all four site/item/field/assignment cases failed. The
updated cases pass without printing injected private values. CLI failures identify the
record in both stderr and unhealthy status, while existing feed and recovery bytes remain
unchanged. A positive Splynx IPv6 range workload still builds exactly 13 addresses.
Installed-wheel checks also exercise malformed records in all three adapters outside the
checkout, alongside the external-input/output publication and unchanged-write workloads.

These are synthetic fixture and CLI checks. No live Sonar, Splynx or phpIPAM state was
changed or measured for this work. Initial adapter support labels remain unchanged.
The [source troubleshooting guide](source-errors.md) separates instance/API-shape problems
from platform capability and explains recovery without partial publication.

## CSV interoperability and large-feed transport

Observed on 2026-11-16 (America/Chicago). Windows ran 189 tests: 187 passed and two
POSIX-only checks skipped. Ten new tests cover generated CRLF, legacy LF compatibility,
malformed endings, exact-hash migration, unchanged writes, bounded Unicode state reads,
oversized responses and sanitized HTTP 413/503 failures. Existing generated-byte tests
now expect CRLF; legacy LF fixtures remain to check backward-compatible recovery.
The stdout control first reproduced a Unicode encoding failure through a Windows-style
text stream. Generation now writes the exact UTF-8 candidate bytes to binary stdout,
avoiding locale encoding and CRLF translation. The printed hash matches those bytes.

The old implementation failed the generation/migration and large Unicode state controls.
A separate HTTP-only control reached the 413 path and proved it lacked actionable size
guidance. After the fixes, both 413 and 503 simulations send one PUT, inspect state/public
delivery and report retained state without leaking server bodies or credentials. A valid
sub-1 MB Unicode fixture produces a state response above 4 MB. It now passes the bounded
8 MB reader; a response above that bound is still refused.

The WordPress offline harness adds CRLF validation, malformed-ending refusal, exact-hash
migration, preserved LF history and conditional recovery back to LF. Installed-wheel checks
also require generated CRLF bytes through the external output adapter and an exact match
from the installed CLI's stdout. Hosted results
are recorded on the PR after upload. No real nginx, database packet-limit or production
WordPress/CDN capacity test was run. The [large-feed runbook](wordpress.md#limits-for-large-feeds)
links primary documentation and calls for a representative staging workload.

## Unchanged publication and destination checks

Observed on 2026-11-15 (America/Chicago). Windows ran 179 tests: 177 passed and two
POSIX-only checks skipped. Fifteen new tests cover unchanged CSV/JSON/WordPress,
recovery-history preservation, public/stored state disagreement, state changes during
verification, local changes before and after replacement, bounded reads, symlink refusal
and destination locking across both state directories and separate processes.

Five new controls first failed against the prior implementation: unchanged publications
overwrote recovery backups, changed WordPress publication did not compare public delivery
with stored state first, and an unchanged run accepted a concurrent stored-state change.
They pass after the changes. Injected concurrent file edits remain intact and cause a failed
result; lock contention blocks the other process rather than reporting healthy publication.
Installed core and external example wheels also passed a workload outside the checkout.
The external output refused a location move, accepted its exact approved candidate, then
verified an unchanged run with identical feed and backup modification times and backup bytes.
The first hosted Windows run exposed different lock keys for short and resolved parent
paths. A portable parent-alias control reproduced the failure locally. Resolving the parent
inside the lock helper fixes both that control and the short-path case.

These are synthetic workloads. Live WordPress/CDN delivery and a production file publisher
remain unmeasured. Local locks coordinate cooperating publishers; they cannot stop arbitrary
editors that ignore them. See [publication verification](publication-verification.md) for
result fields, limits and recovery.

## Location-change guard

Observed on 2026-11-15 (America/Chicago). Windows ran 164 tests: 163 passed and one POSIX-only
skip, including the final preflight-diagnostic test from the base branch.
Fifteen new tests cover country/region/city changes, exact retained coverage by family,
equivalent splits/merges, unsorted rows, row-count distortion, simultaneous withdrawal,
rich coordinates/profile changes and stable Unicode/numeric representations.

The new file and WordPress move tests failed against the previous publishers because a
large location change was accepted. They now refuse the move before writing or replacing
recovery bytes. An IPv6 test proves that one address above a 50% threshold does not round
away. A matching withdrawal-boundary control also exposed rounding in the old removal
comparison; both guards now compare exact integer coverage against decimal thresholds.
A CLI workload checks a blocked move, wrong hash, reviewed exact-hash approval,
status recording and refusal of bogons/large withdrawals despite that approval.

Actual core and external example wheels built and installed in isolation. Outside the
checkout, the installed external target refused a location move, preserved prior bytes,
then accepted the exact reviewed candidate hash. Existing transport/rollback tests now
explicitly permit their intentional test move so they continue exercising write/recovery
behavior rather than stopping at this new earlier guard. No live publication was attempted.

The normal threshold is 10% of retained address coverage per family. It compares all
published location fields, not physical distance. New space and first publication lack a
previous location baseline. Custom targets must enforce the output contract; enabled
extensions remain trusted code. See [location changes](location-changes.md) for review,
one-off candidate approval and recovery without disabling other guards.

## Credential and proxy deployment readiness

Observed on 2026-11-15. Windows ran 148 tests: 147 passed and one POSIX-only skip.
The new tests first reproduced proxy pagination rejection and missing WordPress preflight
guidance, then passed after the fixes. They also test malformed continuations, fixed-origin
requests, no writes after a denied state read, exact ACL parsing and unchanged file selection.

Hosted run [43777130220](https://github.com/MHammett/isp-geofeed-generator/actions/runs/43777130220)
passed six jobs, including a real root systemd workload on disposable Ubuntu 24.04 with
systemd 255.4. Both LoadCredential and LoadCredentialEncrypted loaded the synthetic value
into a service running as UID 65534. Both files stayed root-owned with mode 0440 and the
ordinary file guard rejected them. The systemd-specific reader verified their values.
Explicit unsafe ACL controls refused a group reader, another named UID and other-readable
permissions. No production credential or server was used.

The four Linux jobs ran 148 Python tests, 65 offline PHP checks and deployment coverage.
Installed-wheel multi-input workloads also passed. Target-host Debian/systemd setup and
real WordPress proxy/staging publication still need operator verification. A 401/403 does
not establish which auth/proxy setting is wrong; it stops before writing and gives causes
to investigate. The plugin still requires WordPress's own HTTPS state and does not trust
forwarding headers on its own.

Recovery: leave the last good feed in place, stop scheduling, correct the named access/proxy
configuration and retry discovery/candidate checks. Restore the prior approved package or
web-server config if needed. Do not broaden credential-file permissions or disable HTTPS
to bypass a failed check. See the credential and WordPress runbooks.

## WordPress creation race and phpIPAM setup follow-up

Observed on 2026-11-15. Windows ran 143 tests: 142 passed and one POSIX-only skip. Seven
new phpIPAM tests cover explicit facilities without native locations, missing mappings and
geography, invalid facility settings, subnet failures, unchanged native error handling and
sanitized 401/403 diagnostics. The CLI publishes a configured-location fixture and retains
the prior feed when location data becomes invalid. Tests exposed the missing configured
mode before the implementation; no live phpIPAM instance was available.

PHP syntax and 65 offline WordPress checks passed. Before the fix, the new race test failed
with `concurrent first publication conflicts after stale absent read`. Its add_option stub
models the duplicate-key upsert in the current WordPress source. The corrected plugin uses
an insert that cannot replace a winning option, then preserves the existing conditional
update path. Tests also distinguish first-write/update database failures from conflicts,
check that winning/prior bytes remain intact and keep database details out of responses.

These PHP checks execute in memory with WordPress stubs. They do not load WordPress, touch
its database or prove real staging publication. The native locations endpoint still fails
closed on errors. Configured phpIPAM mode deliberately avoids that endpoint and needs
explicit facilities, reviewed subnet mappings and location values.

Recovery remains the existing last-good-feed procedure. Stop the timer before replacing
packages or a WordPress plugin, retain the prior approved versions and test a candidate or
staging publication before restarting. Other deployment findings remain open.

## Multiple input inventories

Observed on 2026-11-15. The branch builds on the independently reviewed Sonar subnet head
`ef2b8e3`. Windows ran 136 tests: 135 passed and one POSIX-only skip. Fourteen new tests
exercise real built-in Sonar/NetBox adapters with synthetic API replies through the actual
CLI. They generate and publish one combined feed, check per-input IDs and site policies,
and preserve the last good bytes on authentication refusal, missing records, incomplete
paging, empty selection, bad site evidence, overlaps, conflicting locations, bogons and
loss of IPv6. Rich JSON field requirements are tested across both inputs too.

Credential checks cover different endpoints and tokens for two instances of one adapter,
explicit store references, no ambient endpoint/credential fallback, no environment mutation
and shared redaction in errors and failure status. Duplicate YAML keys are rejected so a
repeated input name cannot silently remove an inventory.

Actual core and example extension wheels built and installed in an isolated environment.
Outside the checkout, the installed CLI published a combined fixture using two instances
of the separately installed source extension and the separately installed output extension.
The existing single-source extension/update-preservation tests still pass.

Read-only combined discovery also succeeded using separate existing credential slots:
44 Sonar subnet records and 19 sites, plus 230 NetBox inventory records and 10 sites.
These are inventory measurements, not proof that all selected records have usable public
geolocation. Live combined generation/publication was not attempted. No production data,
service, website or schedule was changed. Consult this branch's PR checks for hosted results.

Recovery and migration are in [multiple inputs](multiple-inputs.md). Site/location enrichment
is not part of this inventory union. The open systemd and WordPress deployment findings remain.

## Sonar subnet and IPv6 follow-up

Observed on 2026-11-15. The branch starts from `f9cfa8a`, the head independently reviewed
by Claude Code in PR #37. That review verified five prior fixes and tested fullbogon lists
and refresh behavior; it did not review this new subnet implementation.

Windows ran 122 tests: 121 passed, with one POSIX-only skip. Sixteen new tests cover exact
IPv6 and IPv4 subnet output, mixed-family and IPv6-only selection, legacy behavior, colliding
native IDs, missing IDs, EXCLUDED subnets, owner types, exact management-IP assignments,
global/disabled controllers, missing/conflicting sites and nested relation paging/count drift.
The CLI workload generates and publishes a dual-stack fixture. It proves missing IDs, lost
site evidence, bogons and withdrawal of the IPv6 family stop publication and retain prior bytes.

A bounded read-only query verified the live Subnet fields and SubnetType values. The new
reader returned 28 pools, 44 subnets and 19 sites. It found 20 dedicated inline-device links
across subnets; seven subnets resolved to one site through management-IP inventory evidence.
The instance had zero IPv6 subnets. Thus the subnet API and site path have live evidence,
while positive IPv6 source data and publication remain synthetic, not measured live.
No Sonar objects, production files, WordPress data or schedules were changed.

Recovery: stop the schedule, keep the last good feed and restore the prior approved package
and configuration. Generate a candidate before any write. Removing the IPv6 family can
trigger the withdrawal guard; a package rollback does not authorize a silent withdrawal.
The current fullbogon check remains mandatory. See [Sonar setup](operator-setup.md#sonar).

## Powercode, gaiia and local extension follow-up

Observed on 2026-11-15. Windows ran 106 tests: 105 passed, one POSIX-only check skipped.
The new tests cover exact Powercode ranges, safe form encoding, gaiia site and block pagination,
missing pages, changed counts, duplicate IDs, archive/ownership conflicts, partial GraphQL errors,
initial-publication blocks and independent extension configuration.

The extension integration test runs the actual publisher in a subprocess using installed-package
metadata outside a temporary core checkout. It first proves that both initial-support opt-ins block
publication. It then publishes, replaces the core runtime, runs again and confirms that the local
configuration, input, extension source and public bytes are intact. This is a simulated core update,
not a production deployment.

The core and example extension built and installed into an isolated environment. Both installed entry
points loaded. The gaiia site, coordinate-site and block queries passed `graphql-core` 3.2.14 validation against the vendor's public
schema; replacing a real address field with a nonexistent field failed the negative control.
Published schema response SHA-256: `8aa25ed901d27232407c520d7ec6f94a2528211b7c76e9ec5c3087498e83262b`.
The export was the anonymous `Introspection` operation used by the vendor's documentation.

No authenticated Powercode or gaiia instance was queried. Real permissions, IPv6 inventory coverage,
server-side truncation and service deployment are not live-verified. Initial support remains explicit.
Consult the adapter pull request for hosted Linux, PHP, packaging and Windows results.

Fullbogon tests refuse interior overlap, unallocated space, stale/future timestamps, malformed
lists and missing reserved-space controls. Failed refresh has no stale fallback; a refused
publication preserves prior output bytes. A read-only fetch of the provider's current data
validated 3,017 IPv4 entries and 158,609 IPv6 entries on this date. The source data is time-sensitive
and is not committed. Offline WordPress checks cover the same static exclusion list as Python,
including broad prefixes containing excluded space. PHP syntax and 58 offline checks passed.

Rich-record tests exercise coordinate bounds, NaN, booleans, partial coordinate pairs, explicit
field projection, incompatible CSV requests, JSON read-back, no-op writes and withdrawal refusal.
Review regressions cover phpIPAM's native location object and private-detail redaction, plus the
NetBox default Token header and sanitized authentication errors. Those adapters remain subject
to the other open review findings. In particular, root/systemd credential loading, WordPress
first-write concurrency and proxy/CDN publication have not passed real deployment trials.
The deployment coverage helper could not run from Windows because its bash invocation
received a Windows path. Linux CI runs that helper; the local Windows attempt is not a pass.

Rollback: stop the schedule, keep the last good public feed and restore the prior approved core package
or compatible extension. The work above did not enable a production schedule or change a website.

## Generic project and source adapters

Evidence updated November 15, 2026.

The table below records the initial implementation at revision
`048ce92164099fe31b425de27687ddeb28e8f4a8`, not later follow-up commits.
The review follow-up adds 11 regression/contract tests: Windows ran 69 tests, with
68 passing and one POSIX-only skip. Consult the [PR checks](https://github.com/MHammett/isp-geofeed-generator/pull/7/checks)
for the current Linux, Windows, PHP and deploy-harness results.
See [the follow-up record](review-followup.md) for the failure cases and remaining limits.

| Check | Result |
| --- | --- |
| Python suite on Linux test host | 58 tests passed, including POSIX secret-file checks |
| Python suite on Windows | 57 checks passed; one POSIX-only test skipped |
| Read-only Sonar controller discovery | Complete pool/site inventory read; controller-to-inventory-to-site path exercised live |
| Read-only NetBox discovery | Prefix/range/site inventory read from 4.7.3; native Windows Credential Manager backend used |
| NetBox missing-scope failure | An unscoped record was rejected as a configuration gap |
| Splynx and phpIPAM | Synthetic adapter, authentication, selection and failure tests; not live-tested |
| Renamed WordPress plugin | PHP syntax and 23 offline contract checks passed |
| Linux deploy harness | 10 runtime modules covered, no extras; dependency-directory canary excluded; 18-line dry run |
| Encrypted credential enrollment/decryption under a new service | Not measured |
| Real WordPress activation, public publication, timer and alerts | Not measured |
| Sonar web interface | Not measured; browser helper failed twice; tracked in issue 6 |
| GitHub Actions | Initial revision passed all five jobs; [run evidence](https://github.com/MHammett/isp-geofeed-generator/actions/runs/43751996141). Consult PR checks for later commits. |

The credential readers were tested for secret redaction, literal-secret rejection, authoritative systemd lookup,
file permissions, symlinks and size limits. The configured operator instance is not assumed to be the ideal data model.
Platform capability and instance readiness are documented separately.

## Original Sonar-only baseline

Evidence recorded November 15, 2026, at 18:29:36 UTC.

| Check | Result |
| --- | --- |
| Python 3.12 on Windows | 36 tests passed |
| Python 3.13 on Linux test host | 36 tests passed |
| Existing restricted service account on Linux test host, with shared lock/status modules | 36 tests passed |
| Deployment coverage | All 6 Python runtime modules covered; no extra modules |
| Dependency-directory leak canary | Present in the test checkout and excluded from deployment |
| Deployment preview | 13 lines; no production install performed |
| PHP syntax on WordPress hosting environment | No syntax errors |
| Offline WordPress validation, capability and CAS checks | 23 checks passed |
| Read-only Sonar discovery against a live v2 instance | Pool/site queries and assignment-candidate queries succeeded |
| Real WordPress plugin activation and public publication | Not measured |
| Actual new service account, timer and failure-alert delivery | Not measured |
| GitHub Actions matrix | Prepared; not yet run |

The tests include malformed data, incomplete pagination, missing mappings, duplicate and overlapping ranges,
nonpublic address space, exact range boundaries, loss of a full address family, stale write hashes,
lost write responses, failed public read-back, failed rollback, and concurrent writers.
HTTP transport tests use a real local HTTP server. They prove that access denial and redirects fail.
The PHP tests use in-memory WordPress stubs and do not change website data.

The service-account test ran from a 33 KB, secret-free source archive in a test stage.
It used the host's existing shared lock and status modules. It did not use production API credentials.
Live discovery used a separate private check; its tenant details and output are not part of this repository.

The repository includes a GitHub Actions matrix for Python 3.11 through 3.14 on Linux and Python 3.12 on Windows.
Those jobs must pass after upload. A successful offline check is not a claim that production publishing works.
