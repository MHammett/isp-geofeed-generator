# Independent review follow-up

## Latest review coverage

Observed from Claude Code's GitHub reviews submitted on 2026-11-16, including the later
later reviews through `52ac290`. Coverage is limited to the work listed
below. BillMax and NIOS now have independent source/contract reviews; neither has a live
tenant/grid test. These reviews are not approval to merge.

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

No defects were reported in those reviewed areas. That result does not fill the listed
gaps. Author evidence, independent probes and live workloads remain separate claims.
Review notes prompted clearer coverage percentages and an explicit Kosovo/XK policy note.

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

- Nested prefixes: rejected consistently by the core and WordPress plugin today. Supporting
  longest-prefix overrides needs one coordinated change to validation, overlap handling,
  coverage calculations, recovery and plugin tests. Do not relax only one check.
  [The proposed contract and acceptance vectors](nested-prefixes.md) specify that work;
  runtime support remains unimplemented and issue #16 stays open.
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
