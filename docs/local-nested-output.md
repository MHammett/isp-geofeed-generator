# Nested local files and recovery

The `file` and `json` targets support explicit longest-prefix locations. WordPress uses
a [separate versioned protocol](wordpress-nested-output.md). Default strict mode is unchanged. This work does not
install anything, change a website or start a schedule. Contributions and sanitized
operator staging results are welcome.

## Configure and verify

Keep your verified inputs, ownership allowlist and current fullbogon settings. Change
only the intended output policy and local path in a private staging configuration:

```yaml
overlap_policy: longest_prefix
state_dir: /var/lib/isp-geofeed-generator/staging
publish:
  type: file
  path: /srv/geofeed-staging/geofeed.csv
```

For rich JSON use `type: json`, its explicit `location_fields`, a `.json` path and the
existing `allow_initial: true` opt-in after testing. Keep one state directory per output
configuration. Keep its location profile stable; use a separate path for profile changes.
Both modes still check every selected parent and child. No name or input order creates
priority. The longest prefix supplies the whole location. Removing a child can move
addresses back to the parent and trigger the location guard.

Generate a private candidate and check its locations before the staging publication.
The printed hash identifies the exact bytes, including the nested CSV marker.

```bash
isp-geofeed-generator generate --config /etc/isp-geofeed-generator/staging.yaml --output /var/lib/isp-geofeed-generator/staging/candidate.csv
isp-geofeed-generator publish --config /etc/isp-geofeed-generator/staging.yaml
```

Run unchanged and verify `changed: false`. Run a changed feed and check guards and
recovery. Local output verifies local bytes and policy only. If a web server hosts the
file, separately check exact bytes, headers and cache behavior on the actual public URL.
Consumer longest-prefix behavior still needs an operator's staging test.

## How old clients are stopped

Nested CSV begins with a version-2 comment containing the policy and a hash of its exact
CSV body. [RFC 8805 section 2.1](https://www.rfc-editor.org/rfc/rfc8805.html#section-2.1)
permits comments. The marker is not an ownership proof or signature. Old project clients
refuse the comment even if the current body has no overlapping rows. Nested rich JSON
uses schema version 2 and an explicit policy, which old schema-1 clients refuse.

A mode-0600 sidecar next to the output binds its exact hash, format and publication ID
to the policy. Protect sidecars from public web serving. New strict publishers also
refuse a destination with bound state. Do not delete the marker or sidecar to bypass
the policy. Private before-data, before-policy and transaction files live in `state_dir`.
Mode 0600 is a POSIX permission setting. On Windows, access depends on the folder's
Windows permissions; keep the state and sidecar folders restricted to the service
account and administrators. A Windows chmod result does not prove a private ACL.

The [Windows replacement guide](windows-file-writes.md) explains the bounded rename
retry for access/sharing denials. Persistent failures still stop, retain recovery
material and require exact pair inspection; the retry does not invent missing policy.

The [metadata guard guide](windows-metadata-guards.md) explains fixed field diagnostics
and Windows handle timestamps. Metadata-only changes still stop immediately; they
are not accepted just because feed bytes match.

Data and sidecar cannot be replaced in one filesystem operation. The destination lock
and exact identity checks protect cooperating writers. An interruption between writes
leaves a mismatched pair, which stops the next run for inspection. The tool does not
invent a missing policy or blindly put an old file back. Arbitrary external file writers
remain outside the cooperating lock contract; detected changes are preserved.

## Conditional recovery

Stop the schedule and inspect the failure first. Keep all private transaction files.
Use the exact candidate SHA-256 printed by the failed operation. Recovery checks the
destination, private baseline, policy, publication ID and current bytes before a write.
It refuses a different writer's bytes or policy. It can finish an interrupted restore
without rewriting bytes already restored by that transaction.

```bash
isp-geofeed-generator recover-local --config /etc/isp-geofeed-generator/staging.yaml --expected-current-sha256 COPY_EXACT_CANDIDATE_SHA256_HERE
```

Recovery reads no input platform and performs no network requests. It restores only the
previously validated local baseline and its policy, including a missing or empty prior
file. It does not prove current source inventory, allocation or public web delivery.
The recovered publication status stays unhealthy until you inspect it and run a normal
verified publication. Recovery does not start a timer.

If recovery is interrupted, inspect the named write problem and repeat the same recovery
command after fixing it. If a concurrent writer wins, keep its output and investigate.
Do not edit the journal or replace its expected hash to force a restore.

## Updates and downgrade

Keep the compatible core, feed and matching policy files together. An unchanged run
preserves output, sidecar, before-data, before-policy and transaction modification times.
An interrupted run reports unhealthy and retains its recovery material.

If the previous baseline is strict, conditional recovery restores that exact strict
file and removes the nested sidecar. If it is also nested, keep the compatible version.
For a planned strict migration, generate and validate a reviewed nonoverlapping feed
at a separate destination, then verify its public route before any service switch.
Never strip markers, drop children or flatten unlike locations just to fit a limit.
Keep issue #16 open for independent review, merge and full operator staging verification.
