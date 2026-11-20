# Independent review follow-up

## Latest review coverage

Observed from Claude Code's GitHub reviews submitted through 2026-11-19, including
the manual-observatory review at `f152f06`. Coverage is limited to the work listed
below. BillMax and NIOS now have independent source/contract reviews; neither has a live
tenant/grid test. These reviews are not approval to merge.

Three RDAP reviews submitted on 2026-11-18 fell between an audit and the author's
later final comments. Those comment times were incorrectly reused as audit cutoffs.
The recovered reviews retain their original dates below. Follow-up audits now compare
all submitted review IDs with this ledger across open and closed PRs, with pagination,
instead of dropping reviews by time. Older records are also added with their original
scope; recording them now does not extend their coverage to later code.

| New or recovered review | Supporting evidence reported | Limits and action |
| --- | --- | --- |
| [#119 manual observatory notes](https://github.com/MHammett/isp-geofeed-generator/pull/119#pullrequestreview-5983426434) | At `f152f06`, read runtime and guide changes, reran 554 Windows tests with two POSIX skips and checked both nine-job runs. Compared two real saved captures with and without notes: local fields and failing exit code stayed the same, except run time/ages. A bad dataset date emitted no JSON report. Independent URL, date, completeness, flag and exit-code mutations were caught. No defects or required follow-up | Duplicate-key, source-name and version mutations also caused errors; they are not pure assertion controls. Removing the explicit file-identity guard was still refused as empty JSON for a missing file. The review does not authenticate manual notes, verify a dashboard API or cover later release/deployment changes. No merge approval given |
| [#117 BlueCat BAM](https://github.com/MHammett/isp-geofeed-generator/pull/117#pullrequestreview-5982792618) | At `235bfad`, read the adapter, wiring, credentials and guide, checked both nine-job runs and independently compared the three public 9.6 pages. Ran 544 Windows tests at the stacked `78eb8d1` with two POSIX skips. Family, host-bit, range, selection, auth and URL mutations were caught. No defects found | The single-resource GET route follows the guide's general collection/ID pattern; no live BlueCat tenant was tested. One string-ID mutation also caused errors, so it is not a pure assertion control. Dropping the type guard was still refused by the family lookup. ASCII account limits are now explicit. Native locations and session lifecycle remain #115/#116. No merge approval given |
| [#118 receipt regression](https://github.com/MHammett/isp-geofeed-generator/pull/118#pullrequestreview-5982793204) | At `78eb8d1`, checked the tests/docs-only diff, reran 544 Windows tests with two POSIX skips and checked both nine-job runs. Independently removing observation/completion equality now caused two failures in 96 registry tests, compared with zero before the follow-up. No defects found | The new mismatch leaves other times ordered, so it covers the specific equality clause. Timestamp wording is corrected. No required follow-up or merge approval. This review does not cover later manual-observatory input |
| [#113 capture importer](https://github.com/MHammett/isp-geofeed-generator/pull/113#pullrequestreview-5982198711) | At `e529202`, read the runtime diff and guide, ran 531 Windows tests with two POSIX skips and checked both nine-job runs. Four earlier real captures passed offline with exact receipt instants and hashes. Tampered copies and independent guard removals checked dates, scope, plans, completeness and combined-input refusal. No runtime defects found | Removing the receipt-observation/completion equality guard escaped existing tests. A dedicated ordered-date mismatch regression and calibrated private guard removal now cover it. The guide clarifies microsecond instant preservation and normalized text. A fully rewritten consistent bundle can still pass, as documented; authenticity and authority remain unmeasured. This review does not cover BlueCat or approve a merge |
| [#108 RDAP capture](https://github.com/MHammett/isp-geofeed-generator/pull/108#pullrequestreview-5980171400) | At `ea43611`, read source, ran 513 Windows tests with two POSIX skips, checked both nine-job runs and made one live capture per RIR. Four HTTP-200 replies were saved and accepted; LACNIC's HTTP 307 was saved and refused. Independently checked hashes, ordered times, validation results and folder/file ACLs. No defects found | Coverage remains at that head, not the later capture importer. Media/encoding and Content-Length mutations each caused a test error rather than a clean assertion catch; the test now raises a fixed assertion on early parser access, with dedicated guard-removal controls. The guide names the observed LACNIC/NIC.br limit without generalizing every Brazilian prefix. No ownership, ingestion or merge approval implied |
| [#110 scoped retry test](https://github.com/MHammett/isp-geofeed-generator/pull/110#pullrequestreview-5980172053) | At `6299b50`, verified no runtime diff, ran 514 Windows tests with two POSIX skips, repeated the ten targeted tests three times and checked both nine-job runs. Independently reverting to a global delay count or keying all delays as policy each caused one failure. No defects found | This verifies the measurement and its regression control. It does not identify the original extra-pause actor or resolve #88. No merge approval given |
| [#104 bootstrap planner](https://github.com/MHammett/isp-geofeed-generator/pull/104#pullrequestreview-5979199273) | At `f06ea78`, reviewed both nine-job runs and source. An independent boundary/brute-force oracle checked 20,695 real-IANA and 16,000 nested synthetic cases with zero mismatches. Three mutations gave 4,031, 1,609 and 150 oracle mismatches and 10, 3 and 5 test failures. No defects found | Real files fetched once per family with original dates/hashes; publication and download dates kept distinct. Reviewer accepts the #96 truncation refusal and #100 mixed-language limit. Optional `--config` refusal is not adopted: standalone diagnostics retain the shared flag while never reading it, as tested. Does not review the later live capture command or approve a merge |
| [#106 OpenWISP](https://github.com/MHammett/isp-geofeed-generator/pull/106#pullrequestreview-5979199637) | At `139065c`, independently checked pinned module routes, fields and canonical network storage, read source, inspected both nine-job runs and ran 497 Windows tests three times. Two full runs passed with two POSIX skips; one failed an older global sleep-count assertion. Five reader mutations produced 4, 9, 4, 3 and 1 failures. No adapter defects found | Auth source was checked on its current default branch, not pinned. No live OpenWISP tenant was tested; initial support remains. Sleep-count isolation is tracked in #109 with a deterministic non-policy-retry control. The original Windows actor is still unmeasured under #88. These findings do not cover later capture code or authorize a merge |
| [#96 saved RDAP](https://github.com/MHammett/isp-geofeed-generator/pull/96#pullrequestreview-5966652162) | Checked source and RFC 9877, both nine-job runs at `24cfb0e`, a 453-test stack run and public registry replies; no defects found | NIC.br returned a geofeed link with policy truncation. Keep the refusal: the returned link does not prove a complete view. A sanitized link-plus-policy-remark control and explicit guide limit are added. Duplicate refusal wording is removed. No operator ownership or untruncated NIC.br view verified |
| [#98 contact redaction](https://github.com/MHammett/isp-geofeed-generator/pull/98#pullrequestreview-5966652631) | Checked both nine-job runs, a 453-test stack run, 14 public RIPE replies and 25 path probes; scope/truncation/family mutations failed assertions; no defects found | Error/media mutations also produced test errors and are not pure assertion controls. This review predates the quoted-string defect and fix. The NIC.br truncation limit still applies |
| [#100 language choice](https://github.com/MHammett/isp-geofeed-generator/pull/100#pullrequestreview-5966653130) | Reran 453 Windows tests, checked both nine-job runs and tested language copies of a real response; exact choice changes coverage; no defects found | The real response's truncation was removed only in the reviewer's local copies, so those are not accepted unmodified live imports. Mixed labeled alternatives and unlabeled singletons remain refused; separate commands lose combined parent/child precedence. That limit and its regression are now explicit. The at-least-one-match mutation was equivalent under unique-label checks |
| [#102 quoted strings](https://github.com/MHammett/isp-geofeed-generator/pull/102#pullrequestreview-5976819514) | Reran 464 Windows tests and checked both nine-job runs; an independent RFC-grammar oracle found zero mismatches in 1.2 million cases; the parent produced 100,298 mismatches in 300,000 cases; three additional mutations caused 15, 15 and 7 failures; no defects found | DEL was excluded because the reader deliberately refuses it. Removing one redundant bound was equivalent and passed the oracle. This verifies quoted-string rules at `7568499`, not the later bootstrap planner. No merge approval was given |
| [#37 initial fixes](https://github.com/MHammett/isp-geofeed-generator/pull/37#pullrequestreview-5913179976) | 106-test Windows run, five hosted jobs, live fullbogon lists and direct location/auth probes verified five fixes; no new extension/field/bogon defects found | One POSIX skip; no local PHP or live Powercode/gaiia/phpIPAM/older-NetBox tenant test; installed-wheel steps were not reviewed in depth |
| [#39 Sonar IPv6](https://github.com/MHammett/isp-geofeed-generator/pull/39#pullrequestreview-5913225109) | 122-test Windows run, five hosted jobs and read-only Sonar schema introspection verified subnet/controller fields; no defects found | One POSIX skip; the inspected instance had no IPv6 subnets, so positive populated-instance publication remains unmeasured |
| [#40 input union](https://github.com/MHammett/isp-geofeed-generator/pull/40#pullrequestreview-5913433163) | 143-test Windows run at the later base, the 136-test hosted head and credential/union/overlap review; no defects found | One POSIX skip; live combined generation/publication was not measured. Coverage applies to those reviewed revisions |
| [#41 publication/phpIPAM](https://github.com/MHammett/isp-geofeed-generator/pull/41#pullrequestreview-5913433297) | 143-test Windows run, hosted PHP results and direct probes confirmed first-write race, token-lifetime and configured-location fixes; no defects found | One POSIX skip; local PHP and live WordPress/phpIPAM were not measured at that review |
| [#90 Windows identity](https://github.com/MHammett/isp-geofeed-generator/pull/90#pullrequestreview-5962181748) | Reran 377 Windows tests with native attribute/ACL observations, checked both hosted runs and source; replacing ctime with zero caused four failures; no defects found | Two POSIX skips. Strict metadata stops and checked recovery remain intact; the outside actor is still unknown under #88. No OS trace or global setting change was authorized |

## Previously recorded coverage

| Review | Supporting evidence reported | Limits still recorded |
| --- | --- | --- |
| [#42 credentials/proxy](https://github.com/MHammett/isp-geofeed-generator/pull/42#pullrequestreview-5921158053) | 212-test suite, seven CI jobs, source inspection and a foreign-next-link probe | New ACL code on target Debian service and live WordPress proxy not measured |
| [#43 relocation](https://github.com/MHammett/isp-geofeed-generator/pull/43#pullrequestreview-5921158589) | Direct IPv4/IPv6 moves, equivalent splits, case changes, first publication and new-space controls | CLI exact-hash approval not independently run; its author tests pass |
| [#45 publication verification](https://github.com/MHammett/isp-geofeed-generator/pull/45#pullrequestreview-5921159001) | Suite and installed-wheel CI evidence | Destination locks/path aliases and real public/stored WordPress state were not reviewed in depth |
| [#46 wire format/limits](https://github.com/MHammett/isp-geofeed-generator/pull/46#pullrequestreview-5921159358) | CRLF/LF/mixed/bare-CR probes and guide review | Real host capacity not measured |
| [#47 source errors](https://github.com/MHammett/isp-geofeed-generator/pull/47#pullrequestreview-5921159765) | New controls fail on old code and pass after the fix | Live billing/IPAM records not measured |
| [#49 ISO/conformance](https://github.com/MHammett/isp-geofeed-generator/pull/49#pullrequestreview-5921160117) | Direct current/replaced/invalid ISO-code probes, suite and CI | Full license text and external-tool setup not reviewed in depth |
| [#50 NetBox models](https://github.com/MHammett/isp-geofeed-generator/pull/50#pullrequestreview-5921885873) | Source review, pinned GeoBox field/schema inspection and 228-test suite at `95164eb` | Neither new mode was tested on a live NetBox; continent-above-country setup note added below |
| [#52 operator notes](https://github.com/MHammett/isp-geofeed-generator/pull/52#pullrequestreview-5921886500) | Reran threshold/display probes, checked Kosovo references and review-scope table | No new live deployment evidence; author and independent checks remain separate |
| [#53 nested-prefix design](https://github.com/MHammett/isp-geofeed-generator/pull/53#pullrequestreview-5921887222) | Compared policy with RFC 8805 and checked unchanged runtime overlap refusal | Reviewer did not hand-check the design fixture vectors; runtime support remains unimplemented |
| [#54 provider plan](https://github.com/MHammett/isp-geofeed-generator/pull/54#pullrequestreview-5921887951) | Checked RDAP standard, IP2Location requirements, ipapi.is receipt semantics and Kosovo references | Other provider rows were not independently checked; no live submission or adapter verified |
| [#55 BillMax](https://github.com/MHammett/isp-geofeed-generator/pull/55#pullrequestreview-5922374612) | Compared every used operation/field with the vendor's Core schema; ran the 253-test suite at `c9e3f79` | No live tenant test; the schema does not establish whether AP networkMask is customer-serving or management-only |
| [#56 NetBox guidance](https://github.com/MHammett/isp-geofeed-generator/pull/56#pullrequestreview-5922375295) | Confirmed the continent example and accuracy of recorded review scope | Docs review; no new live evidence |
| [#58 platform triage](https://github.com/MHammett/isp-geofeed-generator/pull/58#pullrequestreview-5922376165) | Checked NIOS consistency and separation of platform/setup/API/adapter/live gaps | BlueCat, EfficientIP, Incognito and billing-vendor links not independently checked |
| [#59 NIOS](https://github.com/MHammett/isp-geofeed-generator/pull/59#pullrequestreview-5922376957) | Reviewed WAPI use, ran 253 tests and checked public examples of percent-encoded view names | No live grid test, including a spaced view name; public examples are not live verification |
| [#60 adapter follow-up](https://github.com/MHammett/isp-geofeed-generator/pull/60#pullrequestreview-5922591864) | Reran 254 tests and proved the encoded-reference regression fails after loosening its guard | Synthetic contract and documentation checks; no live adapter test |
| [#62 real WordPress](https://github.com/MHammett/isp-geofeed-generator/pull/62#pullrequestreview-5925077906) | Reran 254 tests, checked both hosted integration logs and actual unsafe SQL outcomes, and inspected fixture isolation | Direct HTTP was refused by core before reaching the plugin HTTPS check; no production host or CDN measured |
| [#63 Unicode capacity](https://github.com/MHammett/isp-geofeed-generator/pull/63#pullrequestreview-5925817565) | Checked both actual hosted measurements and refusal controls; modeled later SQL growth | Steady-state estimates are offline models; finite host memory and production capacity remain unmeasured |
| [#64 HTTPS follow-up](https://github.com/MHammett/isp-geofeed-generator/pull/64#pullrequestreview-5925790270) | Verified real core HTTP authentication, the removed-guard commit and restored HTTP refusal/HTTPS success | Disposable stack; actual managed host still unmeasured |
| [#65 interval model](https://github.com/MHammett/isp-geofeed-generator/pull/65#pullrequestreview-5925817949) | Reran 265 tests; independent 3,000-case oracle had zero mismatches; two mutations broke the oracle/tests | Calculation model only at that revision; active nested publication not reviewed |
| [#67 nested core](https://github.com/MHammett/isp-geofeed-generator/pull/67#pullrequestreview-5926438570) | Reran 278 tests; independent 3,000-case guard oracle had zero mismatches; multi-input early refusal, shadowed-parent probes and two mutations | Shipped outputs refused nesting at that revision; later publication work is outside this review |
| [#68 review guidance](https://github.com/MHammett/isp-geofeed-generator/pull/68#pullrequestreview-5926360393) | Checked capacity estimates, canonical/cache-busting guidance and review links | Issue #66 remains open; no managed-host plugin measurement or cache code fix |
| [#69 nested local output](https://github.com/MHammett/isp-geofeed-generator/pull/69#pullrequestreview-5926408601) | Reran 291 tests; 57 independent crash points restored the exact old pair; same-byte other-owner refusal and removed-hash mutation | Windows ACL privacy is not established by mode 0600; WordPress protocol is later work |
| [#71 WordPress policy](https://github.com/MHammett/isp-geofeed-generator/pull/71#pullrequestreview-5937959650) | Four 306-test Windows runs, 89 legacy/37 v2 local PHP checks, direct policy-switch probe and six mutations; four mutations were caught | Offline PHP/Python probes only; reviewer relied on hosted real-WordPress evidence. Two missing regression controls and the recovery exception needed follow-up. Managed-host caching remains unmeasured |
| [#72 restore follow-up](https://github.com/MHammett/isp-geofeed-generator/pull/72#pullrequestreview-5940807247) | Reran 307 tests, local PHP checks and the control script; independently repeated all four guard removals, each caught | Offline controls and hosted evidence inspection; no managed-host purge measurement |
| [#73 cache diagnostics](https://github.com/MHammett/isp-geofeed-generator/pull/73#pullrequestreview-5940807650) | Reran 318 tests; four independent mutations caught; anonymous core-route CDN observations showed fresh/reused query keys and ignored request no-cache | One host's core REST route only; plugin not installed. Later delivery-hook code is outside this review |
| [#75 delivery hook](https://github.com/MHammett/isp-geofeed-generator/pull/75#pullrequestreview-5941819838) | Reran 318 tests, 175 PHP checks and traced post-commit recovery; three of four mutations caught | Empty-feed policy-flip skip lacked a control. WP Rocket defaults and event/runner URL alignment needed clearer guidance. No live provider purge verified |
| [#76 Windows writes](https://github.com/MHammett/isp-geofeed-generator/pull/76#pullrequestreview-5941820308) | Reran 327 tests plus eight clean repeats; 6,000 writes handled 12 native denials with exact byte checks; error-code and wait mutations caught | One workstation and controlled/hosted evidence; blocking process and other-host rates not established. #74 closes after integration |
| [#77 registry references](https://github.com/MHammett/isp-geofeed-generator/pull/77#pullrequestreview-5943389433) | Reran 342 tests and 176 PHP checks; 951 independent IPv4/IPv6 oracle cases had no differences; all six mutations caught; confirmed delivery-skip control and read-only CLI refusals | Unsigned operator snapshots only. Age is reported without an age limit; ranges, signatures and live registry reads remain outside scope. No managed-host measurement |
| [#78 populated-history capacity](https://github.com/MHammett/isp-geofeed-generator/pull/78#pullrequestreview-5944083942) | Independently read both hosted runs and all four stage observations, checked workload logic and unchanged runtime, and modeled SQL size within about 130 bytes | Reviewer did not run the real stack locally. Smaller storage and hash-comparison options require a separate decision and safety tests; actual packet-limit failures and managed hosting remain unmeasured |
| [#79 exact registry ranges](https://github.com/MHammett/isp-geofeed-generator/pull/79#pullrequestreview-5945120143) | Reran 353 tests on Windows; 769 independent model cases had no differences, including 105 crossing refusals; four valid mutations caught and an equivalent-scope tie checked directly | The fifth mutation was malformed and is not verification. No live registry, signature or ownership checks; #80 storage choices remain separate |
| [#81 packet refusal](https://github.com/MHammett/isp-geofeed-generator/pull/81#pullrequestreview-5945298662) | Read the first green push's four packet observations, checked code/docs through `71fb3b8`, compiled Python and linted `hooks.php` locally | No local real-WordPress run; the PR job was still running at the review's observation time. Future storage changes must recalibrate the deliberately failing budget, tracked in #80 |
| [#82 finite PHP memory](https://github.com/MHammett/isp-geofeed-generator/pull/82#pullrequestreview-5945764155) and [final-doc follow-up](https://github.com/MHammett/isp-geofeed-generator/pull/82#issuecomment-6960141139) | Read the test code and first green memory log; checked the PR job result and traced the HTTP 500 path. Later checked docs and run results at `3074b68`, including byte-correct headroom and the empty hard-limit field | Test review at `099aa1a`, docs follow-up at `3074b68`. Only before-commit OOM was exercised at those heads. No local real-WordPress run was claimed |
| [#84 after-commit crashes](https://github.com/MHammett/isp-geofeed-generator/pull/84#pullrequestreview-5946684515) | Read the final code and both hosted logs at `a838b71`; confirmed all ten real crash outcomes, the disabled-allocator control and the cited measurement table; no defects found | Near-limit peaks varied by one 2 MiB block between runs. v1 has no same-byte ownership guard. First-publication crashes, hard kills and managed hosting were unmeasured at that head. This review does not cover later first-publication tests |
| [#86 first-publication crashes](https://github.com/MHammett/isp-geofeed-generator/pull/86#pullrequestreview-5959440925) | Read the final code and both final logs at `c15e482`, plus the docs' cited initial log; confirmed all eight cases, the ordinary-error control and real INSERT/UPDATE checks; no defects found | Small first feeds only. Failed content remains in private stored history after public HTTP 404. Hard kills and managed hosting remain unmeasured. This review does not cover the later storage prototype |
| [#87 storage prototype](https://github.com/MHammett/isp-geofeed-generator/pull/87#pullrequestreview-5961315076) | Read final source and both final logs at `ed6ce48`; confirmed matched inputs, isolation, format round trips, column refusal and exact SQL figures; no defects found | One allocator peak varied by 2 MiB. Which layer refused the legacy write was not measured; optional attribution is tracked under #80. No shipped format or fallback decision was approved |
| [#89 saved RIPE input](https://github.com/MHammett/isp-geofeed-generator/pull/89#pullrequestreview-5961315620) | Reran 369 Windows tests at `bda198d`, read both hosted results and source, and exercised saved public RIPE NCC IPv4/IPv6 lookup/search/parent responses; no defects found | Positive references were added only to local response copies. No private operator prefixes or complete hierarchy verified. Default searches include refused contact objects; exact query flags and the single-file/manual-combination limit needed documentation, added in the later follow-up |
| [#92 multiple registry files](https://github.com/MHammett/isp-geofeed-generator/pull/92#pullrequestreview-5964452587) | Reran 394 Windows tests at `fbad14f`, checked both nine-job runs and full source/docs; six independent date, budget, object and hash mutations were caught; real public RIPE NCC parent/child replies and reversed input order behaved correctly; no defects found | Operator allocations, complete current hierarchy and live ownership remain unmeasured. The requested one-covering-block parent/child recipe is added in the later follow-up. This review does not cover the storage-layer observer |
| [#94 refusal layer](https://github.com/MHammett/isp-geofeed-generator/pull/94#pullrequestreview-5964679560) | Reran 401 Windows tests at `9262442`, inspected both nine-job logs and full source/docs; independently fetched the WordPress core file, matched original/instrumented/restored hashes and the two-line diff; five independent mutations were caught; no defects found | WordPress text validation refused both private direct-format writes before mysqli on this stack. Other hosts may differ; the shipped format still needs its own capability guard if changed. No storage decision was approved. Optional wording request to use Claude's name is applied in the later follow-up |

The #71 follow-up adds isolated wrong-byte and wrong-policy restore refusals in PHP,
plus Python read-back checks for both prior bytes and prior policy. A CI control removes
each guard in a private copy and requires the relevant assertion to fail. The checkout's
runtime code stays unchanged. The disposable WordPress workload also checks those
refusals, exact retained recovery after downgrade and refusal after that baseline leaves
history. Author results remain separate from Claude's earlier-head review. We keep the
publisher recovery exception and document its scope and lifetime in the security and
migration guides. Issues #16, #61 and #66 remain open.

The #72 review confirmed all four requested fixes. The #73 review requested the dated
core-route CDN example now in the [diagnostic guide](wordpress-cache-diagnostics.md).
It does not verify plugin-route caching or a host purge. Issue #74 records Windows
rename denials reproduced in a bare file-writing loop outside this project; the specific
blocking process is not established by that loop. It is separate from the delivery hook.

The #75 notes now have an empty-feed policy-flip control and provider-default/URL-key
guidance. The callback contract and skip behavior remain unchanged. The #76 review
independently confirmed bounded rename handling on the affected workstation. These
reviews do not cover the later registry comparison work.

The NetBox review found no defects and requested one setup example. A hierarchy with a
continent above country has four levels and is refused by the three-level mode. The
[model guide](netbox-location-models.md) now names that case and recommends prefix fields
or site/location mode rather than changing a shared hierarchy. GeoBox users also need
to review unset/false flags and intentionally excluded blank rows before migration;
these remain stopped selected records, not silent omissions.

The BillMax guide now explicitly asks operators to verify the purpose of an AP mask
before publication; syntax and a POP association alone do not establish customer pool
coverage. The NIOS guide and synthetic regression control preserve encoded view names
as opaque references and refuse raw-space substitutes. Neither follow-up upgrades an
initial adapter to live-verified support.

The WordPress review identified a test-coverage gap. Core refuses application passwords
over HTTP in staging, so that refusal alone could not prove the plugin's own HTTPS rule.
A separate fixture now enables core password verification over loopback HTTP with a
private control file. It requires evidence of real publisher authentication, then tests
the plugin refusal, a removed-guard mutation and the restored HTTP/HTTPS behavior.
This follow-up's author workload evidence is recorded separately from Claude's review.

The later HTTPS review confirmed that follow-up closes the coverage gap. The capacity
review identified a limit on the measured example: its SQL size covers the first change
after empty history. The guides now separate that observation from offline steady-state
estimates and require later changed publications in a host capacity trial. The interval
review's independent oracle and mutations are supporting evidence for the model, not
verification of the later core-policy or target work. The new cache issue records
Claude's read-only managed-host observations; plugin-specific behavior there is still
unmeasured. No cache, publication or recovery guard was changed for those observations.

No defects were reported in those reviewed areas. That result does not fill the listed
gaps. Author evidence, independent probes and live workloads remain separate claims.
Review notes prompted clearer coverage percentages and an explicit Kosovo/XK policy note.

The nested-core review requested a parent-fallback refusal test when built-in outputs
gain support. Local CSV, rich JSON and WordPress now have those controls, including a
real WordPress workload. The local-output review prompted a recovery hint for a marked
feed whose policy file is missing, plus a Windows folder-ACL note. These changes keep
the existing refusal and ownership checks. Their author verification is separate from
the reviews of the earlier heads.

[Claude's Geoflaw source check](https://github.com/MHammett/isp-geofeed-generator/issues/70#issuecomment-6928003968)
confirmed the public snapshot facts and added two RFC rules to the plan: native attribute
precedence and unsigned rows limited to the referring object's range. The
[guide](geoflaw.md) records both. No machine integration or registry write is implemented.

## Initial review corrections

Claude Code reviewed revision `048ce92164099fe31b425de27687ddeb28e8f4a8` on 2026-11-15.
The [review and evidence](https://github.com/MHammett/isp-geofeed-generator/issues/1#issuecomment-6900180754)
remain part of the record. The table below records that initial fix set. The proxy row
was later superseded by #42: `next` is only a continuation signal and all requests stay
on the configured origin. Use the current guides and review coverage above for current behavior.

| Finding | Change | Failure check |
| --- | --- | --- |
| Credential helper omitted supported names | Helper uses the same name registry as the reader. | Every supported name appears in enrollment help; the test never prompts for a secret. |
| NetBox proxy emits HTTP pagination links | Same-host, same-path HTTP hints are accepted; the request stays on the configured transport and uses a locally computed offset. | Foreign hosts, paths, ports and unsupported schemes are rejected before a second request. |
| Null NetBox custom fields caused a raw crash | Null becomes absent location data. Malformed field containers fail with the site ID. | Missing country stops generation with an actionable setup error. |
| Other malformed records lacked context | NetBox prefix/range errors and normalized pool/site checks name safe record IDs. Unexpected errors name the current stage without echoing raw values. | Invalid prefix and pool fixtures; forced unexpected failure writes unhealthy publication status without a traceback. |
| Special-space holes | Added explicit exclusions, including the four ranges reported by the reviewer. | Those ranges fail the public-address check; normal IPv4 and IPv6 controls pass. |
| Discovery and generation took the publication lock | Only publication takes the lock. Its owner writes failure status while holding it. | Read commands succeed during a held lock. A second publisher fails and cannot replace the owner's status. |
| User agents showed an old version | Both clients use the package version. | Transport test checks the actual request header. |

Inputs and outputs now have independent registries and contracts. A synthetic input and
target compose through the CLI without platform-specific publication code. Each real input
factory is checked to request only its own credential names. File output requests no secret.

The public systemd template no longer depends on private shared modules, groups or alert units.
Local integrations remain optional drop-ins. The changelog describes an unreleased initial
public implementation instead of an unseen release history. Dependency update configuration
covers Python and GitHub Actions. Repository settings must be checked live, separately from source.

## Design work kept open

- Nested prefixes: explicit support now coordinates candidate validation, exact guards,
  local bound state and the WordPress version-2 protocol in the pending stack.
  [The rollout and acceptance vectors](nested-prefixes.md) describe the contract.
  Issue #16 stays open for review, ordered merges and operator staging. External validator
  acceptance does not prove how a GeoIP provider resolves overlapping rows.
- Location changes: #43 implements a separate retained-coverage guard and exact-candidate
  approval. Its runtime and tests are in the pending stack; the default branch still needs
  that change merged through the owning session before it can be deployed.
- New Sonar pools: unresolved selected public pools continue to stop publication. Configure
  controller evidence or map/exclude the pool. Keeping the old feed is the current safe behavior.
- Sonar IPv6: exact IPv6 generation is tested, but live Sonar pool coverage has not been
  established. Record discovery counts by address family before claiming complete IPv6 support.
- Independent validators: #49 adds shared negative controls, pinned external tools and
  assigned ISO country/subdivision membership. See [conformance](conformance.md).
  Format-only success does not establish valid country codes or real geography.
- GeoIP providers: [the research and interface plan](geoip-providers.md) separates hosting,
  registration, correction receipts and discovery. No provider adapter or registration
  was enabled; issue #24 remains open for implementation and provider lifecycle contracts.

No merge, production installation, timer activation or public feed update is part of this follow-up.
To roll back this source change, use the prior reviewed revision; no live state has changed.
