# Publication verification

The [disposable WordPress integration workload](wordpress-integration.md) exercises
the plugin and runner with a real database and local TLS. It complements the fast
stub tests and does not replace checks of the operator's actual public hosting path.

Each built-in output reads the current destination before publishing. If its exact bytes
match the candidate, the runner verifies them again and skips replacement. It preserves
the existing recovery files. Health status and allocation-cache files may still be updated.
This is an exact-content comparison: a valid feed with different bytes is a change.
Generated CSV now uses CRLF. The updated runner/plugin also read uniform legacy LF;
the first LF-to-CRLF publication changes the hash once and preserves exact LF recovery
bytes. Follow the [plugin-first upgrade and recovery order](wordpress.md#line-endings-and-refresh-policy).

## WordPress

The runner compares authenticated stored state with the unauthenticated public feed before
any write. This catches stale caches and incorrect public routing before a new feed is sent.
If the candidate is unchanged, a second authenticated read must still match. No PUT or DELETE
is sent, and neither `before.csv` nor `last-good.csv` is replaced.

A changed candidate uses the plugin's conditional hash update. The runner then checks both
public delivery and authenticated state. A lost write reply triggers inspection rather than
a blind retry. Recovery uses a conditional update only while the current feed is still the
candidate. A different winning feed is left alone. Both public and stored recovery state must
be verified before the runner reports that the previous feed was retained or restored.

This checks the public route from the runner's network at that moment. It does not prove
that every CDN node or remote geolocation provider has refreshed its copy.

The optional [read-only cache probe](wordpress-cache-diagnostics.md) compares the
canonical route, a fresh query URL and bracketed authenticated state. A probe-only match
is a delivery discrepancy, not a successful publication. Failed or invalid public reads
are reported as not measured. Inspection does not change failed status, private recovery
history or the publisher's normal refusal and rollback behavior.

## Local CSV and rich JSON

The publisher reads a bounded regular file: at most 1 MB for CSV or 8 MB for rich JSON.
Final-component symlinks, devices and files that change during a read are refused. Configure
the actual regular file if the web server exposes it through a symlink.

A lock beside the destination covers the read, comparison, replacement and read-back.
Two generator processes use the same lock even with different state directories. A busy
lock stops the second publisher immediately. The small `.isp-geofeed-*.lock` file stays
in place after release; do not remove it while publishers may be running.

For a changed candidate, the old bytes are saved in the private state directory as
`before.csv` or `before-records.json`. The destination's bytes and file identity are checked
again just before atomic replacement. Read-back must then match the candidate. An unchanged
run replaces neither the public file nor the recovery backup.

Use one publisher account and a dedicated writable destination directory. The lock is
advisory: editors and other programs that ignore it can still race with the final check
and replacement. Trusted directory ownership is required; these checks do not secure a
directory controlled by another user. Local verification proves bytes on disk, so check
the actual public HTTPS path separately before enabling a timer.

## Recovery and result fields

If local read-back fails or another writer changes the destination, the runner fails and
keeps the private backup. It does not blindly restore over a possible concurrent change.
Stop the timer and other writers. Compare the current feed, candidate and private backup.
Restore the reviewed version with the normal guarded publisher or an operator-controlled
atomic replacement, then check local bytes and the public URL before restarting the timer.

The backup holds the baseline of the latest changed publication attempt. An attempt that
stops after saving its baseline may leave that backup even though no replacement occurred.
Keep versioned host backups if more than one prior version is needed. For a WordPress
recovery, follow the [conditional recovery procedure](wordpress.md#manual-rollback).

Successful built-in results include `changed`, `sha256`, `verification` and
`recovery_backup_changed`. Verification is `local-bytes` for file/JSON or
`authenticated-and-public` for WordPress. A failed verification exits with failure; it is
not a healthy unchanged run. Checks describe observed state, not a promise that no later
writer can change it. External targets should follow the same [output contract](adapters.md).
