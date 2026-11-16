# Combine customer and infrastructure space

Use named `inputs` when no single system has the complete inventory. One input can read
customer subnets from Sonar while another reads infrastructure prefixes from NetBox. The
tool combines their selected exact prefixes and publishes one feed.

Start with [config.multiple-inputs.yaml.example](../config.multiple-inputs.yaml.example).
Its addresses are documentation space and cannot be published. Replace them with your
public allocations and choose the source record IDs. Keep private config, state and secrets
outside the Git checkout.

## Configure each input

Each input has a short lowercase name and its own `source`, `url`, `credentials`, `pool_sites`,
`site_locations` and `exclude_pools`. Configure one to 32 inputs, including multiple instances
of the same platform. Every configured input is required. Optional inputs and automatic
fallback are not supported.

Choose either the old top-level `source` or the new `inputs` mapping. Existing single-source
configs still work. In input mode, put mappings and exclusions inside each input; nonempty
global mappings are refused. The allocation allow list, output selection, state directory,
fullbogon policy and withdrawal limit are shared by the combined feed.

Select Sonar `pool_ids` explicitly in input mode, using `[]` for subnet-only reads. Add
`subnet_ids` for intended IPv4/IPv6 service subnets. NetBox can use explicit IDs or a reviewed
tag. Initial adapters and extensions still require `source.allow_initial: true` on that
specific input before publication. Candidate generation can run before this opt-in.

An input's `url` selects its endpoint. Built-in inputs do not fall back to process-wide URL
variables in this mode. gaiia retains its documented public endpoint default. Non-network
extensions need no URL. phpIPAM inputs set `source.app_id` separately. NetBox's explicit
`allow_http` exception still applies; use HTTPS unless your deployment requires that exception.

Credential values never belong in YAML. Each input must name its store references explicitly;
missing references do not use top-level or ambient credentials. For example:

```yaml
credentials:
  SONAR_API_TOKEN: wincred:customer-sonar-token
```

For systemd, use a separate credential slot such as `systemd:EXT_CUSTOMER_SONAR`. The normal
enrollment helper accepts EXT_ names. For environment-based trials, use an explicit alias such
as `env:EXT_CUSTOMER_SONAR`; values still stay outside YAML and command arguments. Different
instances of Sonar can map the same adapter credential name to different slots. Resolved
credentials share the run's error redactor. See [security](security.md), including the open
systemd credential ACL finding before scheduling a service.

## Identity, validation and failures

IDs belong to their named input. Site `11` in Sonar is independent of site `11` in NetBox.
Mappings use each adapter's normal IDs within its own input. No cross-system site or prefix
join is guessed. This mode combines inventories; location enrichment remains future work.

Each required input must return a valid selection with at least one public mapped record.
An API refusal, incomplete page, missing selected record, empty selection or missing location
stops the run. The tool never treats an outage as an empty successful input. Private and
special space is excluded by the existing policy; a private-only input cannot satisfy this
publication requirement. Discovery can still inspect it.

The union rejects duplicate or overlapping prefixes, even if the locations agree. Conflicting
locations are named in the error with both input/record identities. There is no implicit source
priority or automatic deduplication. Fix selection or ownership in private configuration.
The whole combined candidate passes the current fullbogon check. Every selected input must
provide the fields requested by the output, including coordinate pairs where required.

Withdrawal limits are checked on the final feed by address family. Removing a configured
input is a deliberate config change and can trigger that guard. A small withdrawal within
the configured limit is still allowed; this is not a separate per-input withdrawal limit.
Location-change limits compare the final combined feed's retained coverage separately by
family. See [location changes](location-changes.md) for thresholds and exact-candidate approval.

## Check and recover

Run `discover`, then `generate` to a private candidate path, before `publish`. The CLI commands
are unchanged. Discovery JSON groups snapshots by input and records read start/end times.
Private publication status records each input's read boundaries plus record IDs, site IDs,
mapping evidence and exact emitted CIDRs. Public CSV/JSON contains location data, not this
private inventory or credential references.

Reads are sequential. Source APIs do not form a transactional snapshot across platforms.
Avoid major IPAM edits during a run and compare the candidate with both systems. A local file
read-back proves local bytes only; verify public delivery separately.

On failure, keep the last good feed and stop the schedule while fixing the named input.
Restore access, complete its records or correct selection, then generate a fresh candidate.
For a package rollback, restore the prior approved core and its matching config. Older cores
cannot read `inputs`. Do not replace a combined feed with a single-source config without
reviewing the withdrawal. Restoring a package is not permission to bypass the allocation guard.

## Local adapters

Existing entry-point contracts remain version 1. Factories receive the same settings and a
credential-store interface with `get(name)`. Use SDK `source_url(credentials, environment_name,
default)` to honor a named input's endpoint, or wrap built-in sources with `builtin_source`.
Read credentials through the provided store. Legacy extensions that read URLs or secrets
directly from `os.environ` must be updated before using multiple instances. Enabled extensions
remain trusted code with service-account access; this is not a sandbox.
