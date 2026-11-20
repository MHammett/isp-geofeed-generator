# WordPress nested policy and recovery

Core and plugin 0.3.0 add the version-2 policy protocol. Strict output remains the
default. Existing strict version-1 clients and extensions remain supported. Nested
publication needs a compatible plugin, an administrator policy switch and the matching
runner setting. No installer enables it or starts a timer.

## Staging rollout

1. Stop old writers. Back up the site database, plugin, private configuration and recovery
   files. Upgrade the plugin before the runner on staging. Verify strict publication.
2. Preserve the verified current public-feed hash. The public URL remains
   `/wp-json/isp-geofeed-generator/v1/feed`. Check the actual public route and caches.
3. Store a separate administrator application password as `WP_POLICY_ADMIN_APP_PASSWORD`
   through the [secure store](security.md). Set non-secret `WP_POLICY_ADMIN_USERNAME`
   for that operation. The normal publishing account keeps the Geofeed Publisher role.
4. Use a separate private admin configuration for the same site, with
   `overlap_policy: longest_prefix`. Add the admin reference to its existing credentials
   map. Keep the rest of the verified configuration and its other entries. For POSIX:

```yaml
overlap_policy: longest_prefix
credentials:
  WP_POLICY_ADMIN_APP_PASSWORD: file:/etc/isp-geofeed-generator/secrets/wp-policy-admin-password
```

Windows may use `wincred:` instead. Load the admin secret only for the separate policy
operation, not the unattended service. This command reads no billing/IPAM input and
preserves current feed bytes and history:

```bash
isp-geofeed-generator configure-wordpress-policy --config /etc/isp-geofeed-generator/policy-admin.yaml --expected-current-sha256 COPY_VERIFIED_CURRENT_SHA256_HERE
```

It checks stored/public bytes before changing policy. A wrong hash, stale state, wrong
role or missing protocol stops it. An unchanged verified policy makes no write. Even
success leaves publication status unhealthy until a normal publication is verified.

5. Set `overlap_policy: longest_prefix` in the ordinary publisher configuration. Keep
   its publisher credential; it does not need the admin secret. Generate and review
   a private candidate, then publish once on staging:

```bash
isp-geofeed-generator generate --config /etc/isp-geofeed-generator/config.yaml --output /var/lib/isp-geofeed-generator/candidate.csv
isp-geofeed-generator publish --config /etc/isp-geofeed-generator/config.yaml
```

Every raw parent and child still needs valid geography, owned public space and current
fullbogon checks. Exact duplicates stop. Parent fallback can trigger the location guard.
Review intended moves with the existing exact-candidate approval process; it cannot
bypass withdrawals, ownership, allocation or protocol checks.

6. Verify unchanged and changed runs, failure cases and recovery on staging. The
   [disposable integration](wordpress-integration.md) measures one controlled stack,
   not your CDN, persistent cache, host limits or GeoIP provider.

## Read-only inspection

This uses only the publisher credential. It reads no source inventory and changes no
publication status, backup or feed. It compares authenticated state, public bytes and
a second authenticated state. Output contains hashes and policy metadata, not CSV or
credentials:

```bash
isp-geofeed-generator inspect-wordpress --config /etc/isp-geofeed-generator/config.yaml
```

`inspection_only` marks the limited scope, and `feed_present` may be false. A stable or
empty target is not proof of source completeness, ownership or provider ingestion.
A failed publication stays unhealthy. Inspect before deciding on recovery.

Add `--probe-cache` to compare a fresh anonymous query URL as well. The
[cache diagnostic guide](wordpress-cache-diagnostics.md) explains its dated hashes,
unmeasured results and exit codes. A matching query response does not establish normal
public delivery and cannot clear the failed status or alter recovery rules.

## Conditional recovery

Changed runs save private `before.csv` and matching `before-policy.json`, including
destination, candidate hash and publication ID. An unchanged run preserves those files
and `last-good.csv`. Recovery requires the exact candidate ID, bytes, policy and retained
history still to match. A different writer's state is preserved, even with identical CSV.

Stop the schedule and inspect the failure first. After fixing the named cause, use the
ordinary publisher account and the failed candidate's exact hash:

```bash
isp-geofeed-generator recover-wordpress --config /etc/isp-geofeed-generator/config.yaml --expected-current-sha256 COPY_FAILED_CANDIDATE_SHA256_HERE
```

This reads no source inventory. It checks restored public/stored bytes, policy and
history. Lost replies are inspected without blindly repeating writes. Unknown or changed
state stops for attention. Recovery keeps publication status unhealthy and does not
start a timer. If the process stopped before verifying a restore, inspect the state
rather than forcing a hash.

## Strict migration and downgrade

Keep compatible versions throughout migration. Generate a reviewed strictly nonoverlapping
candidate. Set the separate admin configuration to `overlap_policy: reject` and run the
policy command with the verified current hash. The current feed remains unchanged.

Set the ordinary runner to `reject`, then publish the reviewed strict candidate. The
version-2 path compares the old nested map with the new strict map using the same guards.
A failed migration can conditionally restore the prior nested feed and policy. Do not
drop children just to make a feed fit a limit.

We keep this recovery exception so a failed downgrade can be recovered with the
publisher account. The server accepts the exact retained prior CSV and its prior
policy, even when the administrator has selected `reject`. It cannot distinguish a
failed run from an intentional authenticated restore. Anyone holding the publisher
password can therefore bring back that one prior nested feed while it remains in
history. Different bytes or a different prior policy are refused.

An unchanged run preserves that history, so the exception has no time limit. A later
changed publication replaces the one prior feed. Verify both current and prior policies
are strict when you need the nested baseline to stop being restorable. If publisher
access is being withdrawn, stop the runner and revoke that account's application
password as part of the access change. A policy switch alone preserves its recovery
permission. The runner's `recover-wordpress` also requires its private candidate and
ownership metadata; the server exception does not bypass those local checks.

Only consider an older package after public/stored bytes and current policy are strict.
Keep compatible packages and backups for recovery: an old plugin cannot restore a nested
baseline. Never edit state fields or strip the marker to bypass migration checks.

## Technical appendix

Authenticated `/v2/state` and `/v2/feed` use publisher permission. `/v2/policy` requires
HTTPS and `manage_options`. Both writes use the same options-table CAS, with
`INSERT IGNORE` initialization and binary comparison for updates. CSV, accepted policy,
current/prior policy, history and publication ID are stored together. Policy changes
advance the state revision even when CSV is unchanged. Competing operations must leave
one winner rather than a mixed state.

The legacy write route refuses when either accepted or current policy is nested, even
on an empty configured site. The nested CSV marker also stops old readers without
needing overlapping rows. Hashes and publication IDs are concurrency controls, not IP
ownership proofs or RPKI signatures. Reviewed inputs and allowed space remain required.
[Geoflaw](geoflaw.md) adds external discovery diagnostics, not authority or ingestion proof.
