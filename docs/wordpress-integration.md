# Disposable WordPress integration

This test runs the shipped plugin inside real WordPress with MariaDB, PHP workers,
application passwords and a loopback HTTPS proxy. It is separate from the fast PHP
stub suite. Work is tracked in [issue #61](https://github.com/MHammett/isp-geofeed-generator/issues/61).
No production site, credential store or operator inventory is used.

The separate `wordpress-storage-prototype` job runs a [private storage experiment](wordpress-storage-options.md)
for issue #80. It changes only its temporary installed plugin copy and disposable
column. Its measurements do not select or ship a new storage format. The normal job
below keeps the existing escaped format and all of its failure controls.

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

The earlier observations below used unlimited fixture memory. The current harness
uses a finite 256 MiB PHP setting and separate lower-memory controls described in
[the finite-memory workload](#finite-php-memory-workload). Historical measurements
retain their original run, setting and scope.

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

The populated-history observations measure successful statements at the fixture's
normal database budget. The separate packet-refusal stage below lowers that budget
to test a real failure. It does not locate the exact failure threshold. Small-client
and oversized-CSV refusal controls remain separate checks. No production database
or web-server setting is changed.

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
They are not maximum bounds. HTTP PHP still reported unlimited test-runner memory.
At that revision, finite memory, actual packet-limit failures, production proxies and
CDN behavior remained unmeasured. The later packet-refusal workload below adds one
controlled failure budget. Keep staging checks and packet headroom even if your first
update succeeds.

## Packet-refusal workload

Each populated-history case now tests its next update at an 8 MiB database packet
budget. A disposable-only local socket command saves the original global setting,
lowers it, and reads it back. A private fixture header also reads the actual HTTP
request's database session setting. A setting that could not be measured does not pass.
The [MariaDB variable is dynamic globally, but not for an existing session](https://mariadb.com/docs/server/server-management/variables-and-modes/server-system-variables#max_allowed_packet).

The prepared statement must exceed the smaller budget and fit the original one.
The runner must send one PUT and receive the real plugin's HTTP 503 `geofeed_db`
response. Its status must stay unhealthy and name database/packet limits without
exposing credentials. Read-only diagnosis then checks the exact stored document,
public CSV and private recovery baseline before the budget is restored. The v2 case
also checks private baseline policy and owner metadata.

The original setting is restored in `finally`, even when a check fails. After the
restored setting and unchanged baseline are measured, an explicit new publication of
the same CSV must succeed. It must execute a same-sized prepared statement, verify
exact current and previous stored/public bytes, and record verified recovery history.
Both the failing and successful PUTs must report the expected database session budget.
`PACKET LIMIT OBSERVATION` logs contain fixed codes, counts and sizes, not SQL or CSV.

One runner PUT is not proof of one low-level database attempt. The `query` filter
counts calls into `wpdb`, while [WordPress can reconnect and replay a query internally](https://developer.wordpress.org/reference/classes/wpdb/query/).
Raw driver attempts remain `not_measured`. The test does not disable that core behavior
or claim to measure it. No proxy-generated failure replaces the real database refusal.

This is a controlled disposable-host experiment. It does not authorize changing a
production limit, prove a universal minimum, or measure finite memory, a CDN or a
managed host. On an operator's staging path, stop the timer after a capacity failure,
inspect the named layer, verify the prior stored/public baseline, and have the database
administrator check the actual statement and limits before a deliberate new run.

### Measured packet refusal and correction

On 2026-11-17, [hosted run 44159141685](https://github.com/MHammett/isp-geofeed-generator/actions/runs/44159141685)
at `936a3d1` passed all eight jobs. All four cases reported an actual HTTP database
session budget of **8,388,608 bytes** for the failed PUT and **16,777,216 bytes** for
the successful corrected PUT. The latter was the fixture's saved original setting.

| API / UTF-8 bytes per character | Prepared SQL bytes, failed and corrected |
| --- | ---: |
| v1 / 3 | 8,584,900 |
| v2 / 3 | 8,585,878 |
| v1 / 4 | 12,836,434 |
| v2 / 4 | 12,837,412 |

These are later statements after the deliberate public-read-back recovery, rather
than stage 3 in the earlier table. Each failed run made one runner PUT and received
the origin plugin's HTTP 503 `geofeed_db` result. The exact database document, including
history and policy/owner state, and public baseline remained unchanged. Private CSV
recovery bytes remained exact, and the v2 private baseline kept the correct policy
and owner. The failed status stayed unhealthy and included safe database-size guidance.

At the measured restored budget, each explicit new run published the same CSV with
the same prepared-statement size, one runner PUT and verified current/prior/public
bytes. It then recorded healthy status and the correct private recovery history.
Each phase made one call through the geofeed query filter. Raw driver attempts were
not counted, so no claim is made about internal database retries.

This measures refusal at one deliberately undersized budget and success after a
verified correction. It does not find a universal minimum. Finite PHP memory was not
measured at that revision; the later stage below adds that check. Total host memory,
production limits and managed-host/CDN behavior still need operator staging checks.
The plugin, publisher and storage encoding are unchanged.

## Finite PHP memory workload

The fixture sets PHP `memory_limit`, `WP_MEMORY_LIMIT` and `WP_MAX_MEMORY_LIMIT` to
`256M` before WordPress loads. Its startup response must report the real HTTP value.
The whole workload runs with that finite setting. This changes only the disposable
test configuration. The plugin, publisher and production defaults are untouched.

Two small changed publications, one per API, must also pass at `64M`. They run real
authentication, CSV validation, database commit and public verification. This proves
the lower setting can run a small feed before testing a near-limit feed at that budget.
It is more than a liveness check.

Each of the four large-feed cases then attempts its next update at `64M`. A private
fixture control applies the lower setting only to feed PUTs. GETs and the private CLI
retain `256M` so preflight and read-only diagnosis remain available. The test therefore
measures exhaustion in the write path, not exhaustion of every route on a host.

A shutdown callback is registered before core's fatal handler, with a small reserved
allocation released for logging. It records only API version, actual PHP setting, peak
allocation, an exhaustion flag and the raw hard-limit directive when available. It
never writes the fatal message, SQL, CSV or credentials. The exhaustion flag requires
a real PHP fatal memory error; a proxy-generated HTTP 500 cannot satisfy it.

The failed run must stay unhealthy, make one runner PUT and preserve the full stored
document, public CSV and private recovery baseline. The v2 private baseline must keep
the correct policy and owner. The fixture restores its normal control in `finally`.
After checking that control and the unchanged baseline, a deliberate new run of the
same candidate must succeed at the observed `256M` setting. Stored current/prior bytes,
public CSV, private history and policy fields must all match.

`memory_limit` is not a promise that observed allocation never crosses that number.
[PHP documents deferred fatal handling and a separate hard-limit setting](https://www.php.net/manual/en/ini.core.php#ini.memory-limit).
The test records actual peaks and requires actual exhaustion rather than assuming a
peak must be below the configured threshold. `hard_limit_percent` is the raw directive;
`null` means it was unavailable. It is not a measured process-memory ceiling.

The peak comes from [PHP's allocator measurement](https://www.php.net/manual/en/function.memory-get-peak-usage.php),
not whole-process RSS or total host memory. Kernel/container OOM kills, hard-limit
termination without a shutdown callback, multiple workers' combined memory, plugins
on another host and managed-host/CDN behavior remain unmeasured. Missing shutdown
evidence fails the check. These synthetic budgets are not host sizing recommendations.

### Measured finite-memory exhaustion and correction

On 2026-11-17, [hosted run 44165181249](https://github.com/MHammett/isp-geofeed-generator/actions/runs/44165181249)
at `099aa1a` passed all eight jobs. WordPress 7.1.4, PHP 8.3.6 and MariaDB 10.11.14
ran the full workload with `256M` configured. Both small changed publications passed
at `64M`, each with a 44,040,192-byte PHP allocator peak and no exhaustion.

The four large cases each produced a real PHP fatal memory record, HTTP 500 and an
unhealthy runner result at `64M`. Each made one runner PUT and zero calls through the
geofeed write-query filter. The exact raw stored document, public baseline and private
recovery bytes were preserved. The v2 baseline also retained the correct policy and
publication owner. After the normal control and unchanged baseline were checked, each
explicit new run of the same CSV passed at the observed `256M` setting.

| API / UTF-8 bytes per character | Peak bytes before fatal at `64M` | Peak bytes on successful correction at `256M` |
| --- | ---: | ---: |
| v1 / 3 | 72,519,680 | 97,316,864 |
| v2 / 3 | 72,523,776 | 97,320,960 |
| v1 / 4 | 65,445,888 | 109,502,464 |
| v2 / 4 | 65,445,888 | 109,506,560 |

The configured 64 MiB threshold is 67,108,864 bytes. The three-byte cases peaked above
it before the fatal handler ran. A failed allocation also need not appear in the peak.
The runtime returned an empty string for the hard-limit directive, so no numeric hard
ceiling was measured. These observations are why the test separates settings, actual
peaks and fatal evidence instead of treating the setting as a strict peak bound.

Two early controls stopped correctly rather than reporting success. The `32M` small
publication prerequisite failed. At `64M`, an assertion that the peak must stay below
the configured threshold was disproved by the recorded fatal peak and was corrected.
The final controls still require real exhaustion, exact baseline preservation and
same-candidate success at the finite corrected setting. The fixed lower budget must
be recalibrated if a future storage change makes these workloads fit without exhaustion.

These are synthetic single-request measurements. They do not establish a host minimum,
whole-process RSS, combined worker capacity or behavior after a hard kill. No production
limit, plugin or publisher behavior was changed.

## After-commit PHP exhaustion

The [issue #83](https://github.com/MHammett/isp-geofeed-generator/issues/83) workload
tests a different boundary: the feed is already saved, but PHP exhausts memory before
the response finishes. It uses the existing post-commit action in the installed fixture.
No plugin, publisher, role or permission check is replaced.

The private one-shot control names a nonce, API version and expected candidate/history
hashes. The hook reads the real saved document and checks those values before consuming
the control. It then measures current allocation, sets a finite threshold 16 MiB above
the rounded allocation, and reads the setting back. The threshold must be no more than
192 MiB within the normal `256M` fixture. At most 48 one-MiB chunks are attempted.
If PHP does not raise an actual fatal memory error, the control fails.

The existing early shutdown logger must record the real fatal at the measured setting.
A second direct fixture read then captures the committed candidate before the proxy
delivers the real HTTP 500 to the runner. The proxy does not substitute an error response.
Logs expose fixed hashes, policies, publication identities and allocation sizes, never
CSV, SQL, passwords or raw fatal text. The request peak may include earlier publication
work done before the threshold was lowered; these fault budgets are not host sizing data.

| Scenario | APIs | Cases | Runner HTTP statuses | Required outcome |
| --- | --- | ---: | --- | --- |
| Recover small and near-limit Unicode feeds | v1, v2 | 4 | 500, 200 | Exact prior feed restored; failed run stays unhealthy |
| Publisher wins before inspection | v1, v2 | 2 | 500 | New publication preserved; no restore attempted |
| Publisher wins immediately before restore | v1, v2 | 2 | 500, 409 | Stale restore refused; winner preserved |
| Administrator wins before inspection | v2 | 1 | 500 | Identical candidate bytes with a new policy/owner preserved |
| Administrator changes policy and changes it back before restore | v2 | 1 | 500, 409 | Identical bytes and policy with a new owner still block the stale restore |

Race actors use real authenticated backend API calls after the original fatal response
has reached the proxy. Restore-window actors run after the runner has inspected its
candidate but before its restore reaches the server. The interception checks that the
outgoing request is the justified baseline restore, not a repeated publication.
The v2 policy round trip isolates identity protection even when bytes and policy match.
The v1 races test competing changed bytes; they do not establish same-byte owner identity
protection for the legacy byte-comparison protocol.

All cases check exact stored/public state, retained history, policies where applicable,
private baseline bytes and unchanged last-good bytes/modification time. The crash control
must be gone before restoration or a competing write. Only the original request may
have an exhaustion record. Each recovery case then publishes the same candidate normally
and verifies it at `256M`, without rearming the fault. That deliberate new run is separate
from the failed run, whose result remains unhealthy even after verified restoration.

Before the ten real crashes, a negative control disables the allocator only in the
installed temporary MU-plugin copy. It must actually commit, consume the fault and return
an ordinary HTTP 503 callback error with no OOM records. The after-commit crash assertion
must fail at the intended check, while normal conditional recovery preserves the baseline.
The exact fixture source is restored before the ten real cases. Thus an ordinary callback
exception cannot pass as a real memory crash, and the checkout is never mutated by the
control.

Controls and interception callbacks are removed in `finally` and on close. These are
changed-publication tests on the disposable loopback stack. The separate first-publication
workload below covers recovery to an empty feed. Hard process/kernel kills, whole-host
capacity and managed-host/CDN behavior remain separate from this evidence.

### Measured after-commit crash and ownership outcomes

On 2026-11-17, [hosted run 44174167353](https://github.com/MHammett/isp-geofeed-generator/actions/runs/44174167353)
at `f62f705` passed all eight jobs. The disabled-allocator control reached the saved
candidate, consumed its one-shot flag, returned an ordinary callback HTTP 503 and
recorded no OOM. Crash verification failed at the intended assertion, and the runner
restored the baseline. The intact installed fixture then passed all ten real cases.

Four cases restored the prior feed after the real HTTP 500, with runner statuses
`[500, 200]`. The failed runs stayed unhealthy, kept exact private baseline/last-good
history, and later published the same candidate normally with the fault removed.
The near-limit candidate CSVs were 980,432 bytes for v1 and 980,567 bytes for v2.

Six races preserved the other actor's exact raw state and public bytes. Three happened
before inspection and made no runner restore attempt (`[500]`). Three happened just
before restore and received a real server refusal (`[500, 409]`). This includes the
v2 administrator round trip: candidate bytes and required policy returned to their
earlier values, but the new publication identity still blocked the stale restore.
Those runs stopped unhealthy with recovery needing attention.

| Workload, both APIs | Current allocation after commit | Lowered fault threshold | Earlier request peak | Peak after fatal |
| --- | ---: | ---: | ---: | ---: |
| Small feed | 44,040,192 | 60,817,408 | 44,040,192 | 60,817,408 |
| Near-limit Unicode feed | 75,796,480 | 93,323,264 | 95,895,552 | 95,895,552 |

These are PHP allocator byte counts in this injected-fault experiment. The near-limit
request had already peaked above its later fault threshold during normal publication.
That is why a peak alone cannot prove when or why an OOM happened. The real fatal
record, consumed nonce-bound control, saved document and independent pre-response read
were all required. No sizing recommendation follows from these artificial thresholds.

Each failure cycle made two geofeed query-filter calls: the candidate plus its restore
or the competing actor. The admin round-trip case made three because the administrator
made two real policy changes. The three stale restores were refused before another
geofeed write query. These counts do not measure raw driver retries. No restore or
competing feed request had a second OOM record. First-publication crashes were unmeasured
at that revision; the separate workload below adds that coverage. Hard kills, total host
memory and the actual managed-host/CDN path remain unmeasured.

### First-publication crash workload

Issue [#85](https://github.com/MHammett/isp-geofeed-generator/issues/85) tracks the
empty-baseline path. A first publication cannot recover by uploading an old feed.
It must conditionally DELETE only its own failed candidate. The public route then
returns HTTP 404. The empty document retains the failed candidate in history; this
does not remove all database evidence of the attempt.

The v1 trial starts with no document row. Its first feed write must be an actual
INSERT. The v2 trial starts with an administrator-configured empty policy row, since
nested publication requires that opt-in. Its first feed write is an UPDATE. In v2,
the empty baseline uses `reject` while the required policy is `longest_prefix`.
Recovery must restore that exact pair and the failed candidate's history, with a
new owner ID. Treating both policies as interchangeable would miss this case.

Eight small-feed cases reuse the bounded, consumed fault and independent pre-response
snapshot above. Two recover through real DELETE requests, keep the run unhealthy,
verify public HTTP 404 and then publish the same candidate in a deliberate normal
run. Six protect a publisher or administrator before inspection or just before DELETE.
The administrator round trip restores the same bytes and policy with a new owner ID;
that ID must still block the stale DELETE. v1 tests changed competing bytes because
it has no owner ID.

Each failed first run must leave an exact empty private `before.csv` and no
`last-good.csv`. V2 also checks the original empty baseline's owner, both policies
and the failed candidate's owner in private recovery metadata. The shutdown logger
records feed DELETEs as well as PUTs, so the test verifies that recovery runs at the
normal `256M` setting without another OOM. Lower-memory before-commit controls still
apply only to PUTs.

A separate disabled-allocator control starts with the empty v2 baseline. It must
commit, consume the flag, return an ordinary HTTP 503, safely DELETE its candidate
and fail the real-crash assertion. It must record no OOM. The exact installed fixture
is restored before the eight genuine crashes. This keeps an ordinary callback failure
from passing as a first-publication fatal crash.

On 2026-11-18, [hosted run 44330999200](https://github.com/MHammett/isp-geofeed-generator/actions/runs/44330999200)
at `b920e40` passed all eight jobs and all eight first-publication cases. The two
recoveries used runner methods `PUT, DELETE` with origin statuses `500, 200` and
verified public HTTP 404. Both then verified the same candidate normally. Three
competing actors won before inspection, so no DELETE was sent (`500` only). Three
won just before DELETE, which received origin HTTP 409 (`500, 409`). Each winner's
raw stored document and public bytes stayed exact. All failed runs remained unhealthy.

The ordinary-error control returned `503, 200` for `PUT, DELETE`, recorded no OOM,
returned public HTTP 404 and failed the intended real-crash assertion. The eight
genuine crashes each measured 44,040,192 bytes allocated before the fault, lowered
the limit to 60,817,408 bytes and recorded that same fatal peak. These small synthetic
requests and artificial thresholds are timing/failure evidence, not host sizing.

No publisher, plugin or storage behavior changes for these checks. They cover small
first publications on the disposable loopback stack. Near-limit first publications,
hard process kills, whole-host capacity and managed-host/CDN paths remain unmeasured.

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
