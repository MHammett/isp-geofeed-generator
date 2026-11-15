# Verification

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
