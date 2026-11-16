# Coordinated nested-prefix support

Status: core candidate/guard support for issue #16. Built-in nested publication is
not implemented. The default remains `overlap_policy: reject` everywhere. Private
generation, parsing and merging can use an explicit `overlap_policy: longest_prefix`.
All shipped output targets still refuse that mode before reading inputs or credentials.
Do not remove a target check to enable it.

## Core policy and extension contract

Set the top-level `overlap_policy` explicitly to `longest_prefix` to generate a private
nested candidate. It applies to the entire combined inventory. Input order does not
set priority. Exact duplicates still stop with source IDs, and each raw parent and child
must pass ownership, location and fullbogon checks. Selected nonpublic records stop a
nested run unless deliberately excluded. Normal CSV/JSON byte limits and the combined
50,000-record limit still apply. An approval hash can approve a location move only.

The core CSV change guard uses the effective interval model for both withdrawal and
relocation in nested mode. The public `effective_change_guard` SDK helper provides the
same exact counts and limits for an explicit rich profile. Child removal can count as
a move through parent fallback. Default strict behavior remains available for old clients.

Version-1 extensions remain supported in `extensions.targets` and cannot declare nested
support. A version-2 target uses `TargetAdapter(api_version=2, overlap_policies=...)`,
the `isp_geofeed_generator.targets.v2` entry-point group and the separate opt-in list
`extensions.targets_v2`. It receives `overlap_policy` as an explicit publish keyword,
including `reject` in strict mode. Unknown versions/policies and mismatched discovery
groups stop. Sources retain their version-1 contract. Trusted extensions remain code
installed by the operator, not a sandbox.

Declaring a capability is a target author's contract, not proof of a live service. A
version-2 target must bind policy to state/history, check exact stored/public bytes,
refuse incompatible writers and recover conditionally. Shipped targets do not advertise
nested support yet because that work is incomplete. Do not wrap an old file/WordPress
publisher and label it capable. Existing version-1 wrappers keep their old strict calls.

## Calculation groundwork

The private `_effective` module implements the interval calculation below. Core nested
guards now call it. The internal module is not a public extension API or an alternate
publication validator; use the documented guard helper for a version-2 extension.

The model validates canonical raw prefixes and complete locations for an explicit
profile, refuses exact duplicates and uses the longest prefix's whole location. It
keeps the winning raw record's ordinal as private provenance. Coarse fields are the
default; a rich profile must be requested explicitly. Extra fields are refused rather
than silently dropped. Locations use the existing validation and NFC normalization.

A sorted boundary sweep takes O(N log N) work and O(N) memory. At most 50,000 raw
records produce 100,000 boundary events and at most that many intervals. The model
never enumerates addresses or turns intervals into serialized CIDRs. Endpoints and
counts are exact integers, including the exclusive IPv6 endpoint 2^128. A count-export
helper emits decimal strings for JSON consumers.

This calculation does not establish ownership, allocation or public-address eligibility.
Those checks remain mandatory on every raw prefix before any future publication path
can use it. The active no-bogon and overlap protections remain unchanged. Generic IP
boundary tests are analysis cases, not addresses permitted in a feed.

Tests cover the six design vectors, a separate bounded address-by-address oracle,
full IPv6 nesting depth, exact one-address threshold excess, mixed families, all 50,000
records and the first excess record. A broadest-prefix mutation must break the design
vectors. Actual publication parsing still refuses the nested examples.

## Operator policy

RFC 8805 allows a broad prefix with a more-specific location. In the explicit nested
mode, the longest matching prefix would provide the whole location for an address.
Input order, platform and record ID would not decide priority. The default would remain
strict rejection. A target that cannot verify this policy would stop before writing.

For example, a /24 can name City A while one contained /25 names City B. Half the addresses
then use each city. Removing the /25 makes those addresses fall back to City A. That is
a location change, even though no address disappears from the /24's coverage.

The complete rollout must include the core, SDK contract, every enabled target, WordPress,
read-back, recovery and operating instructions. Old clients must fail safely. This design
does not approve a merge, deployment, provider registration or change to a real feed.

## Decisions

| Question | Proposed rule |
| --- | --- |
| Default behavior | Reject all overlaps, as today |
| Opt-in | A new explicit overlap policy, negotiated with the target; configuration names are not final |
| Priority | Longest prefix wins within each address family |
| Duplicate exact prefix | Refuse, even with identical location data or different input names |
| Partial child location | Refuse; do not inherit individual fields from a parent |
| Blank/no-location child | Refuse under the present output policy; no new tombstone semantics |
| Missing selected input/record | Stop the whole run |
| Special/unallocated/unauthorized space | Check every raw prefix in full; a child cannot make a bad parent safe |
| Automatic range expansion | Never; keep exact source range conversion |
| Unsupported custom target | Stop before backup or upload; no implicit flattening |
| Withdrawal and location approval | Keep separate per-family limits and exact-candidate review; approval never enables nesting or weakens other guards |

Explicit source selection remains required. Nested mode would apply to the final combined
inventory, including Sonar and NetBox together. Cross-input duplicates still stop with
both input names and safe record IDs. An operator must select the intended broad and
specific publication units deliberately. No adapter may create a broad parent just to
fill a gap or inherit a location from a name.

## Coverage and change rules

Metrics must use the effective location of each address, after longest-prefix selection.
They must not sum raw prefix sizes, which double-counts a child inside a parent.

- Coverage is the union of published address intervals, separately for IPv4 and IPv6.
- Withdrawal is old coverage missing from the new union, divided by old coverage.
- Retained coverage is the intersection of the old and new unions.
- Relocation is retained coverage whose complete published location changes, divided by
  retained coverage. Use the existing normalization of text/numbers and exact thresholds.
- Removing an override can relocate addresses through parent fallback. Removing a parent
  while keeping a child can withdraw addresses outside that child.
- Adding a same-location child, equivalent splits or equivalent merges must not create a
  false move. A parent location edit affects only addresses not overridden by a child.
- First publication and newly covered addresses have no prior location baseline. They
  still pass every selection, schema, ISO, ownership, allocation and target-policy check.

For a 256-address parent and a 128-address child, profiles A, B and C mean complete,
validated output locations. These are test examples, not real allocation claims.

| Old rows | New rows | Removed | Retained | Relocated |
| --- | --- | --- | --- | --- |
| Parent A | Parent A, child B | 0 | 256 | 128 (50%) |
| Parent A | Parent A, child A | 0 | 256 | 0 |
| Parent A, child B | Parent A | 0 | 256 | 128 (50%) |
| Parent A, child B | Child B | 128 (50%) | 128 | 0 |
| Parent A, child B | Parent C, child B | 0 | 256 | 128 (50%) |
| One /24 A | Two /25s A | 0 | 256 | 0 |

Machine-readable IPv4 acceptance vectors are in `tests/fixtures/nested-prefix-design.json`.
Their expected metrics are checked against the private model and a bounded reference
calculation. They are a design oracle, not a statement that the current parser accepts
the rows. IPv6 calculation tests include exact one-address threshold excesses, /128 and
broad parents, and mixed-family cases. Current strict tests keep refusing overlaps.

## Technical appendix: implementation contract

Create one shared effective-interval layer. It should produce sorted, disjoint intervals
with complete normalized location signatures and private source provenance. Use bounded
prefix/event processing or a trie. Never enumerate addresses, allocate arrays by address
count, or force internal intervals into a huge flattened feed. Enforce work/record budgets
and test worst-case IPv6 nesting depth and near-limit input sizes.

Generation, CSV/JSON parsing, cross-input merging, withdrawal and relocation must all use
the same policy. Keep validation of every raw record before deriving effective intervals.
Preserve deterministic serialized ordering and exact payload hashes. Metrics use integer
endpoints and rational thresholds; display rounding has no effect. If counts are exported
in JSON, encode large integers as decimal strings so JavaScript cannot round them.

Targets need a versioned capability declaration for nested semantics. Existing version-1
extensions default to unsupported. Source contracts can still return raw validated records;
they must not independently choose priority or flatten conflicts. The SDK publisher must
receive and enforce the chosen policy. An extension that cannot do so fails before writes.

WordPress needs authenticated policy/capability metadata and a write-protocol check, in
addition to its exact CSV hash and conditional database update. A server configured for
the new protocol must reject an incompatible client before a write, even if the current
document is empty. Policy and feed history must be stored/updated together. Preserve the
first-write INSERT IGNORE race protection, conditional later writes and safe database errors.
Changing policy during publication must cause a conflict, not silently change semantics.

Public read-back must return the exact candidate bytes. The client must parse them under
the negotiated policy and confirm authenticated state after public delivery. Recovery
must conditionally restore the exact prior feed and its policy only while the candidate
still owns the destination. Unknown/concurrent state remains untouched and unhealthy.

Local publication needs matching private policy state bound to the payload hash. A missing
or mismatched pair must trigger inspection, not an assumed policy. Retain the existing
destination lock, exact pre-replacement checks and refusal of blind restoration. Test
crashes between file and policy-state writes. No-op runs must preserve both recovery files.

## Rollout and recovery gates

Before enabling a nested run, generate a private candidate, resolve every duplicate and
verify every required target's declared support. Review the effective location map and
per-family guard metrics. A provider accepting nested syntax is not proof it applies
longest-prefix behavior; test each real public/consumer path separately.

Keep old clients and schedules stopped during the switch. Take the required host/plugin
backup, preserve feed plus policy state, then upgrade compatible core/SDK/plugin versions.
Run a full staging workload: initial publish, changed publish, no-op, failed read-back,
lost reply, policy mismatch, concurrent writer and conditional recovery. Only then enable
the private opt-in. No installer may turn nesting on automatically.

Before downgrade, restore a reviewed strictly nonoverlapping feed and matching policy
using compatible tooling. A flattened equivalent may exceed the 1 MB output limit, so
verify capacity before using it as a recovery plan. If safe conversion is too large,
keep the compatible versions and schedule stopped while an operator chooses a recovery
publication. Never drop child rows or merge unlike locations just to fit a limit.

## Acceptance checklist and open implementation work

Issue #16 stays open until the coordinated implementation and all gates below are done.
This design does not claim that feature is shipped.

- Keep default overlap rejection and same-CIDR duplicate refusal in core and plugin.
- Integrate the private effective-interval model into all policy-aware paths, with
  exact IPv6 boundaries and no double-counted coverage. Calculation tests alone do not
  establish that publication, withdrawal or relocation uses it.
- Add explicit target/SDK capabilities and old-client/old-plugin failure controls.
- Carry policy through WordPress CAS/history, public/stored read-back and checked recovery.
- Bind local policy state to file hashes, lock it and test interrupted state updates.
- Test valid and conflicting cross-input nesting, selected-source failure, ISO/ownership/
  fullbogon refusals and approval attempts that must not bypass those protections.
- Verify all built-in output formats, enabled custom targets, size/work limits and no-op
  backup preservation. Run installed-wheel and real PHP workloads with negative controls.
- Obtain independent review and operator staging evidence before any production opt-in.

Source: [RFC 8805 section 2.1.3](https://www.rfc-editor.org/rfc/rfc8805.html#section-2.1.3).
Prior-art inheritance and no-location behavior is a separate policy choice; neither is
adopted by this proposal. Publishing source prefixes still does not prove IP ownership
or actual customer geography.
