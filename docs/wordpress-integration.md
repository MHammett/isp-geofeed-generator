# Disposable WordPress integration

This test runs the shipped plugin inside real WordPress with MariaDB, PHP workers,
application passwords and a loopback HTTPS proxy. It is separate from the fast PHP
stub suite. Work is tracked in [issue #61](https://github.com/MHammett/isp-geofeed-generator/issues/61).
No production site, credential store or operator inventory is used.

## What runs

The `wordpress-integration` job uses a disposable GitHub-hosted Ubuntu 24.04 runner.
It installs PHP/MariaDB from the runner's package sources and downloads the official
WordPress archive named in `tests/wordpress/core.json`. The archive must match the
pinned SHA-256 before extraction. Expanded size, entry count, paths and symlinks are
checked. The installed core version must match the pin.

WordPress 7.1.4 was selected from the official release API on 2026-11-16. It is a test
pin, not a promise to test every supported WordPress release. To refresh it, verify a
current official release, download and hash that exact archive, update the pin, then
run the complete workload. Never replace the hash check with an unpinned `latest` URL.
See [WordPress authentication](https://developer.wordpress.org/rest-api/using-the-rest-api/authentication/)
and the APIs for [installing a site](https://developer.wordpress.org/reference/functions/wp_install/)
and [creating application passwords](https://developer.wordpress.org/reference/classes/wp_application_passwords/create_new_application_password/).

The fixture creates a random local database and a user limited to it. Temporary admin,
publisher and subscriber credentials are generated for that site. The publisher has
the real plugin role; authentication and permission checks are not replaced. Bootstrap
uses WordPress APIs rather than a manually populated mock options table.

The HTTP backend and HTTPS front listener bind only to `127.0.0.1`. The front uses a
one-day certificate trusted by the test client. TLS verification stays enabled. A
private test-only proxy marker lets WordPress recognize requests from that front.
The proxy overwrites client forwarding/marker headers. A direct HTTP request with only
a forged forwarding header must still be refused. This marker is fixture machinery,
not a configuration recipe for a production proxy.

All fixture files, keys, accounts, logs, state and inventory live under a private
temporary directory. Control files and CLI helpers are outside the web document root.
No fixture is copied into the shipped plugin or normal deployment. Mail and outbound
WordPress HTTP requests are disabled. The database/user and worker process group are
removed at the end; the disposable runner is also discarded. No credential-bearing
artifacts are uploaded.

## Workloads and negative controls

- Real authenticated first and changed CLI publication, followed by unauthenticated
  CSV read-back and checks of content type, cache policy and exact CRLF bytes.
- An unchanged CLI run with the same database document, no geofeed SQL write attempt,
  and unchanged local recovery bytes and modification times.
- Anonymous, subscriber, incorrect-password and direct-HTTP write refusals. A positive
  publisher workload must also succeed; denial alone cannot count as a passing setup.
- Invalid ISO, overlapping/duplicate and bogon payloads rejected by the real REST route
  without changing stored data.
- Competing first inserts and later updates. Two real PHP workers meet at a bounded
  barrier immediately before the geofeed write. Exactly one request must succeed;
  the database must preserve its bytes and the correct prior document.
- Test-only unsafe SQL mutations must break those race checks. Replacing the protected
  first insert can overwrite a winner; removing the binary comparison can admit two
  case-only updates on a case-insensitive database. The original plugin is restored
  before each passing control and verified afterward.
- A stale public preflight with no database write or local recovery-history change.
- A corrupted public read-back after a real commit and a lost successful write reply,
  each followed by checked conditional recovery.
- A second real authenticated writer winning during recovery. The runner must leave
  that winner in place and report that recovery needs attention.
- Refused recovery, with candidate bytes still present, the old private recovery
  baseline retained and unhealthy status. A failed recovery cannot count as restored.

The race/fault hooks live only under `tests/wordpress/`. They do not add an HTTP control
route or bypass authentication. Query instrumentation records verbs and process IDs,
not SQL, authorization headers, credentials or feed data. Each forced fault must be
observed; an untriggered fault is a failed test.
HTTP workers have opcode caching disabled for the mutation controls. The harness checks
that setting through an HTTP response and requires the intended SQL verbs at the barrier.
Editing a file while a worker still runs cached code does not count as a mutation test.

The full generator CLI uses the separately installed synthetic-input extension. Its
normal ownership, ISO, overlap and publication guards run. Fresh synthetic fullbogon
files isolate this workload from a third party's availability; the independent policy
and external-validator jobs remain separate checks.

## Running and interpreting it

The supported execution path is the GitHub-hosted workflow. The harness refuses Windows,
other operating systems and non-hosted runners before importing application code or
creating a database. A refusal is **not measured**, not a healthy integration result.
Missing PHP, database tools or TLS prerequisites fail the job. It does not silently skip.

The job prints installed WordPress, PHP and database versions, a marker for each real
workload, and one final integration marker only after all assertions pass. A green
download, install or HTTP readiness check alone is insufficient. Inspect the workload
markers and negative controls in the run log when recording evidence.

This verifies one controlled WordPress/database/proxy stack. It does not measure an
operator's actual CDN, host limits, persistent object-cache plugin, multisite setup,
replica lag or production TLS configuration. Keep the existing staging and public-path
checks in [the setup guide](wordpress.md). This harness is not a production installer.
