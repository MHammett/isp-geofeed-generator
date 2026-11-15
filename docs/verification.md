# Verification

## Powercode, gaiia and local extension follow-up

Observed on 2026-11-15. Windows ran 93 tests: 92 passed, one POSIX-only check skipped.
The new tests cover exact Powercode ranges, safe form encoding, gaiia site and block pagination,
missing pages, changed counts, duplicate IDs, archive/ownership conflicts, partial GraphQL errors,
initial-publication blocks and independent extension configuration.

The extension integration test runs the actual publisher in a subprocess using installed-package
metadata outside a temporary core checkout. It first proves that both initial-support opt-ins block
publication. It then publishes, replaces the core runtime, runs again and confirms that the local
configuration, input, extension source and public bytes are intact. This is a simulated core update,
not a production deployment.

The core and example extension built and installed into an isolated environment. Both installed entry
points loaded. The two gaiia queries passed `graphql-core` 3.2.14 validation against the vendor's public
schema; replacing a real address field with a nonexistent field failed the negative control.
Published schema response SHA-256: `8aa25ed901d27232407c520d7ec6f94a2528211b7c76e9ec5c3087498e83262b`.
The export was the anonymous `Introspection` operation used by the vendor's documentation.

No authenticated Powercode or gaiia instance was queried. Real permissions, IPv6 inventory coverage,
server-side truncation and service deployment are not live-verified. Initial support remains explicit.
Consult the adapter pull request for hosted Linux, PHP, packaging and Windows results.

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
| Python suite on scripting1 | 58 tests passed, including POSIX secret-file checks |
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
| Python 3.13 on scripting1 | 36 tests passed |
| Existing restricted service account on scripting1, with shared lock/status modules | 36 tests passed |
| Deployment coverage | All 6 Python runtime modules covered; no extra modules |
| Dependency-directory leak canary | Present in the test checkout and excluded from deployment |
| Deployment preview | 13 lines; no production install performed |
| PHP syntax at WP Engine | No syntax errors |
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
