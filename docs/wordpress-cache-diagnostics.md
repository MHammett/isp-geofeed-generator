# Read-only WordPress cache diagnostics

Use this after a public/stored mismatch and before choosing recovery or changing a
cache setting. Stop the schedule and preserve the failed publication's recovery files.
The command reads the paired 0.3.0 plugin's state and public feed. It does not read the
configured billing/IPAM source, publish, restore, purge a cache or clear failure status.

In Bash on Linux, with the ordinary publisher credential available through its existing
secure store:

```bash
isp-geofeed-generator inspect-wordpress --config /etc/isp-geofeed-generator/config.yaml --probe-cache
```

PowerShell on Windows uses the same installed command and arguments with its private
configuration path. No administrator password is needed. The plain `inspect-wordpress`
command still checks only the normal public URL unless `--probe-cache` is requested.
The flag is refused for publication and other commands before any configuration is read.

## What it measures

Two authenticated state reads bracket two anonymous GETs: the normal
public feed and the same route with a fresh `isp_geofeed_probe` query value. The state
comparison includes policy, publication ID and history, not just current CSV. There
are no retries or redirects. The normal TLS, content-type, 1 MB and feed-validation
limits apply to both public reads.

Output includes a UTC `observed_at`, hashes, policy metadata and the finding below.
It omits CSV, remote response bodies, headers and credentials. These are observations
from the runner's path at that time. A query-string response may itself come from a
cache or different routing rule; it does not prove origin freshness or that the
normal URL has refreshed.

| `delivery_finding` | Meaning and next step |
| --- | --- |
| `both_match` | Both public responses matched stable authenticated state. Continue the host's other staging checks. |
| `canonical_differs_probe_matches` | The normal route differed while the fresh query matched. Investigate cache keys, rewrite rules and edge behavior. |
| `canonical_unavailable_probe_matches` | The normal read or validation failed while the query matched. Investigate the normal route; its bytes were not measured. |
| `both_differ_same_bytes` | Both responses returned the same valid bytes, but those differed from stored state. Investigate routing and shared caches. |
| `both_differ_different_bytes` | The two public responses differed from each other and stored state. Inspect both public paths. |
| `probe_differs` | The normal URL matched, but the query URL differed. The additional diagnostic is inconsistent. |
| `state_changed` | Current/prior bytes, policy or owner changed during inspection. Repeat only after investigating other writers. |
| `state_recheck_unavailable` | The second authenticated state read failed. Stability is not measured. |
| `probe_unavailable`, `canonical_differs_probe_unavailable`, `public_read_unavailable` | One or both reads failed validation or could not be read. Their match/hash fields are null. |

Without the optional probe, findings are `canonical_matches` or `canonical_differs`,
subject to the same unavailable/state-change outcomes. `cache_probe_requested` separates
an unrequested probe from a failed one. Measured public reads mean validated CSV or the
existing empty-feed HTTP 404 result. `feed_present: false` names an empty target.

Exit code 0 and `inspection_consistent: true` mean the requested observations matched
stable state. They do not establish publication health, input completeness, ownership,
real geography or provider ingestion. Any mismatch or unmeasured requested check exits 1.
An existing unhealthy publication status remains unchanged in either case.

## Recover and investigate

Keep the original candidate hash and private recovery files. Use the existing
[conditional recovery commands](wordpress-nested-output.md#conditional-recovery) when
recovery is appropriate. Do not force a hash or replace history based only on a probe.
The publisher's preflight, read-back, health and conditional rollback rules are unchanged.

Compare anonymous headers on the actual normal route with the host's supported tools.
Verify cache behavior on staging before changing it, then run a changed publication,
an unchanged one and a recovery trial. A successful query URL alone is insufficient.
The plugin's `no-store` header can still be overridden outside the application.

[Issue #66](https://github.com/MHammett/isp-geofeed-generator/issues/66) stays open for
managed-host measurement, any supported purge integration and decisions about recovery
when delivery differs. No automatic purge or change to rollback is part of this command.
