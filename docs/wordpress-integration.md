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
- A separate plugin HTTPS control. A private fixture file temporarily lets WordPress
  core verify real application passwords over loopback HTTP. The authenticated publisher
  must then receive HTTP 403 from the plugin, with no geofeed writes. Removing only the
  plugin's HTTPS guard in the private copy must permit a real HTTP write and break that
  refusal check. Restoring the plugin must refuse HTTP again while allowing HTTPS.
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
- Near-limit Unicode first and changed CLI publications, followed by an unchanged
  run with no geofeed SQL writes or recovery-history changes. Measure CSV, upload JSON,
  state JSON and SQL bytes separately. Record the actual HTTP PHP and database limits.
- First and three changed near-limit publications for both API versions, using
  three-byte and four-byte Unicode city characters. Measure each stage separately,
  including updates whose old and new documents both contain full history. Repeat
  unchanged without HTTP or SQL writes. Force a public mismatch after a later change
  and verify exact stored/public recovery while the failed run stays unhealthy.
- A deliberately smaller state-response budget must refuse the large response without
  writes. An otherwise valid CSV above the plugin's byte limit must receive HTTP 400
  and preserve the stored/public feed. Neither refusal can count as successful publication.

The race/fault hooks live only under `tests/wordpress/`. They do not add an HTTP control
route or bypass passwords or roles. The core transport exception above is controlled
by a private file outside the web root, applies only to the disposable loopback fixture
and is removed in `finally`. It is not copied into the shipped plugin. The test records
that core actually authenticated the publisher before trusting the plugin's refusal.
The original direct-HTTP case alone measures core's transport refusal, not the plugin's
HTTPS guard. Query instrumentation records verbs, process IDs
and statement byte counts, not SQL, authorization headers, credentials or feed data. Each forced fault must be
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

## Measured large-feed example

Hosted run [43926425105](https://github.com/MHammett/isp-geofeed-generator/actions/runs/43926425105)
on 2026-11-16 used 4,735 synthetic records with a 60-character Unicode city. Both
current and previous feeds were near the CSV limit. WordPress 7.1.4, PHP 8.3.6 and
MariaDB 10.11.14 completed first/change/unchanged publication.

| Measurement | Bytes or observed setting |
| --- | --- |
| Current CSV | 980,230 bytes |
| Largest upload JSON | 1,842,098 bytes |
| Authenticated state JSON | 3,693,183 bytes |
| Largest geofeed SQL statement, first change after empty history | 6,434,412 bytes |
| Database `max_allowed_packet` | 16,777,216 bytes |
| HTTP PHP `post_max_size` | `8M` |
| HTTP PHP `memory_limit` | `-1` (unlimited in this test runner) |

The normal client accepted the state. A client capped at the former 2,000,000-byte
budget failed at its response-size guard without writes. A CSV above 1,000,000 bytes
received HTTP 400 from the real plugin and left the large feed intact. An unchanged
run kept the exact database document and local recovery bytes and modification times.

These are measured values for this input and controlled stack, not worst-case bounds
or a recommendation to remove memory limits. The test proxy allows larger request
bodies than a default production proxy. Finite host memory, CDN limits, packet limits
and timeouts still need a representative staging workload on the operator's own path.

The measured change started with an empty history field. A later changed publication
carries two feeds in the new document and two in the old conditional-comparison document.
Its SQL statement can therefore be much larger. Include at least three changed near-limit
publications in a capacity trial, so both current and prior history are populated.

[Claude's independent review](https://github.com/MHammett/isp-geofeed-generator/pull/63#pullrequestreview-5925817565)
modeled about 8.58 MB for a steady-state update using three-byte city characters and
12.83 MB with four-byte characters. Those are offline model estimates, not additional
hosted measurements or universal maximums. A 4 MB or 8 MB packet budget can fail a later
update even when the first publications passed. Measure the actual statement and leave
headroom; keep the setup guide's separate server/client budget checks.

The harness now emits four `STEADY CAPACITY` observations, one for each Unicode width
and API version. Each observation records four publication stages, plus an unchanged
run and recovery from a forced public mismatch. The version-2 case uses the configured
`longest_prefix` policy and its versioned payload; separate workloads test actual
overlapping records. Stage 0 starts with empty feed history. Stages 2 and 3 compare
populated old and new history. These logs contain byte counts, not SQL or feed data.

The recovery control must observe one bad public response, one publication PUT and
one conditional restore PUT. It then checks the exact database/public baseline and
private recovery files. Recovery does not turn that failed run healthy. The unchanged
control checks every private state file except the status report, including bytes and
modification times, and makes no HTTP writes or geofeed SQL writes.

This workload measures successful statements at the fixture's database budget. It does
not lower the server's packet budget or establish the exact failure threshold. The
small-client and oversized-CSV refusal controls remain separate checks. No production
database or web-server setting is changed.

## Measured populated-history workloads

On 2026-11-17, [hosted run 44138616802](https://github.com/MHammett/isp-geofeed-generator/actions/runs/44138616802)
at `fd18752` passed all eight jobs. WordPress 7.1.4, PHP 8.3.6 and MariaDB 10.11.14
completed all four workloads. The table shows stage 3, the last normal changed feed.
The city field contains 60 copies of a three-byte or four-byte Unicode character.
These are synthetic encoding workloads, not actual customer locations.

| API / UTF-8 bytes per character | CSV bytes | Upload JSON bytes | State JSON bytes | SQL statement bytes |
| --- | ---: | ---: | ---: | ---: |
| v1 / 3 | 980,646 | 1,842,878 | 3,694,829 | 8,582,176 |
| v2 / 3 | 980,781 | 1,843,314 | 3,695,271 | 8,583,154 |
| v1 / 4 | 980,966 | 2,752,896 | 5,512,384 | 12,831,196 |
| v2 / 4 | 981,101 | 2,753,332 | 5,512,826 | 12,832,174 |

For v1 with three-byte characters, the SQL grew from 2,144,741 bytes on first
publication to 6,434,412 on the first change and 8,580,360 on the next change.
With four-byte characters, the same stages were 3,206,158, 9,619,082 and 12,827,704
bytes. The test database reported a 16,777,216-byte packet budget. Successful commits
and exact stored/public read-back were checked, rather than statement size alone.

Every case then repeated unchanged with zero HTTP writes and zero geofeed SQL writes.
All private state files except the status report kept their exact bytes and modification
times. A later forced public mismatch made one publish PUT and one conditional restore
PUT. Exact prior stored/public bytes were restored, and the failed run stayed unhealthy.
The v2 cases also kept the required, current and prior overlap policies intact.

These measurements replace the earlier model's evidence gap for these four inputs.
They are not maximum bounds. HTTP PHP still reported unlimited test-runner memory;
finite memory, actual packet-limit failures, production proxies and CDN behavior remain
unmeasured. Keep staging checks and packet headroom even if your first update succeeds.

## Version-2 policy workload

The 0.3.0 workload also runs the real policy commands with separate administrator and
publisher accounts. It checks default refusal, exact-hash setup, unchanged setup with
no SQL write, old-client refusal and unchanged feed/history. Removing a child triggers
the parent-fallback location guard before any publication write.

Competing initial policy inserts, feed updates and administrator-versus-publisher
updates must leave one complete winner. Stale policy and owner IDs are refused. Faults
include bad public bytes, lost replies, another publisher, refused recovery and an
administrator owning identical candidate bytes. Recovery must preserve that other
owner. Separate trials restore strict and empty baselines and migrate back to strict
output with the exact-candidate location approval.

The administrator HTTPS control first proves core authenticated the HTTP administrator.
The plugin must refuse the write. Removing only that route's HTTPS check must allow an
actual HTTP policy commit; restoring it must again refuse HTTP and permit HTTPS.
This is separate from the publisher's HTTPS mutation control.

Read-only inspection after recovery must leave the unhealthy publication status and
its modification time intact. These workloads run only on the disposable stack. See
the [rollout and recovery guide](wordpress-nested-output.md) before host staging.

## Read-only cache inspection workload

The separate delivery-action workload holds canonical cached bytes until a real installed
WordPress callback records a purge. It tests both write APIs, unchanged runs, recovery
and deletion. Removing each API's notification must leave stale public bytes and fail
publication. A throwing callback and an accepted but ineffective callback must also fail
without losing the saved baseline. This is a synthetic cache, not a managed-host purge
measurement or a live WP Rocket test.

The disposable proxy injects stale canonical bytes, stale bytes on both public URLs
and an unavailable canonical route. A control forwards both URLs unchanged. The real
CLI must distinguish the four outcomes using exactly two authenticated state GETs and
two anonymous public GETs. Every case must preserve the exact stored document, SQL
write log, failed status and private recovery files. Its configured source file is
removed before inspection, proving that the command does not need source inventory.

These injected outcomes verify diagnostics only. They do not measure a managed host's
cache policy or prove that a query response came from origin. The diagnostic cannot
change publication health or the publisher's rollback behavior.
