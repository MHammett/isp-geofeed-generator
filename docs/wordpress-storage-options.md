# WordPress storage decision

Issue [#80](https://github.com/MHammett/isp-geofeed-generator/issues/80) asks whether
smaller stored JSON is worth a format change. The shipped plugin still uses escaped
JSON and compares the complete old document before replacing it. This guide and its
private CI experiment do not change that behavior.

## What the experiment changes

The separate `wordpress-storage-prototype` job creates a new disposable WordPress
site. It first runs the current plugin. It then changes only that site's temporary
plugin copy to store Unicode and slashes without JSON escapes. The checkout's plugin
file stays intact. The full-document binary comparison and first-insert guard stay
intact in both copies.

The experiment measures the same near-limit input on both APIs, using three-byte and
four-byte city characters. Each case publishes its first feed and three changes,
runs unchanged, and recovers from a forced public mismatch. It checks exact public,
stored and private recovery bytes. The unchanged run must make no writes and preserve
private recovery file times. Successful recovery still leaves the failed run unhealthy.

It records CSV, upload JSON, response JSON, stored document and prepared SQL bytes.
It also records actual PHP allocation peaks under the normal finite `256M` setting.
HTTP connections must report `utf8mb4` for client, connection and results. Column
metadata is measured through the private CLI fixture. Allocator peaks are not process
RSS or total host memory, and no timing or throughput claim follows from these runs.

An original-encoder control must fail the stored-format assertion before the real
direct-Unicode trials. Separate small cases read escaped documents with the prototype,
recover a failed direct publication, then use the original plugin to read and replace
the direct document. This tests both directions without converting existing data in
place.

## Measured comparison

On 2026-11-18, the prototype job in [run 44341755100](https://github.com/MHammett/isp-geofeed-generator/actions/runs/44341755100)
at `398f7d1` passed. The table shows the third changed publication, with populated
history on both sides of the conditional update. All sizes are bytes.

| API | Bytes per city character | CSV | Current escaped SQL | Direct-Unicode SQL |
| --- | ---: | ---: | ---: | ---: |
| v1 | 3 | 980,646 | 8,582,176 | 3,997,728 |
| v2 | 3 | 980,781 | 8,583,154 | 3,998,706 |
| v1 | 4 | 980,966 | 12,831,196 | 3,981,796 |
| v2 | 4 | 981,101 | 12,832,174 | 3,982,774 |

The SQL reduction was about 53% for the three-byte cases and 69% for the four-byte
cases. The stored document fell from roughly 3.69 MB or 5.51 MB to about 1.98 MB.
Both APIs showed the same PHP allocation peaks at this stage: 97,300,480 to
74,719,232 bytes for three-byte characters, and 109,481,984 to 75,378,688 for
four-byte characters. These are measured examples, not maximum bounds or a memory
setting recommendation.

Upload and authenticated state-response sizes did not change. This option alone
does not reduce proxy upload limits or the client's response budget. It changes
stored JSON and conditional SQL, while WordPress still encodes its API responses.

All eight capacity cases passed their exact-byte, unchanged-run and conditional
recovery checks. Four small format round trips also passed, including direct-format
recovery after reading an escaped document. Both three-byte-column trials returned
HTTP 503 for the private direct format and then published the same candidate with
the original escaped plugin on the unchanged column. The encoder negative control
failed the intended format assertion, and the PHP isolation guard refused an actual
column-change request without changing column metadata. The original plugin and
column metadata were restored, and an original-format publication passed afterward.

The first attempt stopped after its negative control on a folder-name error in the
harness. That path was fixed. Synthetic migration/charset inputs were also kept at
the same geography with growing coverage, so the existing relocation and removal
guards could stay enabled. Those guards and the shipped plugin were not weakened.

## The older-column case

A real three-byte options column is tested with a measured `utf8mb4` connection.
The current escaped plugin first publishes four-byte city characters successfully.
The private direct-Unicode prototype then attempts a larger feed with the same
geography. That attempt must fail with HTTP 503 and preserve the exact old stored,
public and private baseline. It must make one runner write and remain unhealthy.

The original escaped plugin must publish that same candidate on the unchanged
three-byte column. This separates a format compatibility limit from WordPress's
ability to publish those characters. It is not evidence that an operator must convert
their database to use the current tool.

Only the private CLI fixture can change the disposable column, using a fixed list of
collations. Python refuses outside the hosted disposable environment. PHP also refuses
outside explicit prototype mode. A real refused PHP action must leave column metadata
unchanged. The original plugin and exact original column metadata are restored in
`finally`; a real original-format publication must then pass. The temporary site and
database are removed when the workload closes.

## Choices that remain open

| Choice | Operational effect | Work needed before shipping |
| --- | --- | --- |
| Keep escaped JSON | Keeps existing compatibility. Large conditional writes still need the measured packet and memory budgets. | No format rollout. Continue host capacity checks. |
| Direct Unicode with escaped fallback | Could reduce storage and SQL on compatible instances while retaining support for older columns. Two formats would remain supported. | A reliable column and live connection capability check, safe fallback rules, full race and failure controls, and operator staging. |
| Direct Unicode with refusal | Could reduce writes on compatible instances. An older instance that works today could stop until its configuration changes. | Explicit setup requirements, a verified refusal before any unsafe write, full race and failure controls, and operator staging. |

No fallback or refusal policy has been selected. Do not convert a production table
or install the private experiment as an optimization. Current operators can keep
using escaped storage. A format change needs a separate reviewed implementation and
an approved rollout.

The other option in #80, comparing a digest of the exact stored document, changes a
different part of the conditional write. This experiment does not implement or verify
that option. Its ownership, history and concurrency design remains separate.

## Limits before a shipped change

The prototype does not establish support for every column/connection combination,
all racing writers, changed database privileges, persistent object caches or managed
hosts. The normal integration job still runs the existing packet, finite-memory,
ownership and crash controls against the shipped escaped format. Passing those tests
does not verify the private prototype under the same faults.

A real format change must run those controls against the new implementation. It must
recalibrate deliberately failing packet and memory budgets if smaller writes fit the
old failure settings. Keep a measured failure and the same-candidate positive control.
Do not loosen those checks just because storage gets smaller. Public read-back,
credential controls and conditional recovery remain required.

## Source contracts

[WordPress documents](https://developer.wordpress.org/reference/functions/wp_json_encode/)
that `wp_json_encode` accepts encoding flags and defaults to zero.
[PHP defines](https://www.php.net/manual/en/json.constants.php) the unescaped Unicode
and slash flags used only in the private experiment.
[MariaDB distinguishes](https://mariadb.com/docs/server/reference/data-types/string-data-types/character-sets/unicode)
three-byte `utf8mb3` from four-byte `utf8mb4`. Its `utf8` alias can depend on server
configuration, so the experiment checks the actual returned column metadata.

No merge, deployment, production schema change or feed update is part of this work.
