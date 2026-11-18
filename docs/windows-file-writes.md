# Windows file replacement failures

On Windows, a file held without delete sharing can temporarily block replacement.
Issue [#74](https://github.com/MHammett/isp-geofeed-generator/issues/74) records failures
reproduced in a bare writing loop outside this project. That separates the observed
denial from the feed logic. It does not identify which process held the file, and its
measured frequency is not a prediction for other hosts.

## Bounded local retry

The shared atomic writer creates, writes, flushes and closes one temporary file in the
destination folder. Only the final `os.replace` is eligible for a retry:

- Windows only, with `PermissionError` and Windows code `5`, `32` or `33`.
- At most five rename attempts per file replacement, with 50 ms between attempts.
  That adds at most 200 ms of programmed waiting per file, plus filesystem and guard time.
- The same prepared temporary file and destination are used. The data is not rewritten,
  re-sent or re-flushed for each attempt.
- Any existing destination/policy check runs before every attempt, including after a
  wait. A competing change or guard failure stops immediately.

[Microsoft's error list](https://learn.microsoft.com/en-us/windows/win32/debug/system-error-codes--0-499-)
names these as access denied, sharing violation and lock violation. Access denied can
also mean a lasting permission problem. The retry does not assume the cause is harmless.
Other errors, failures of the guard itself and POSIX replacement failures are not retried.
A persistent denial is raised after the budget. Normal temporary-file cleanup still
runs and can itself fail; preserve any remaining private temporary file for inspection.
Cleanup failures are not retried by this change.

SDK callers must keep `before_replace` a read-only precondition that is safe to repeat.
It can run before each attempt. Do not put a purge, remote write or other side effect
in that callback.

The retry does not change ACLs, relax file validation, remove a destination lock or
disable a scanner. Trusted directory ownership and cooperating-writer locks remain
required. External programs can still race between a check and a replacement.
Python documents the replacement operation in [the `os.replace` reference](https://docs.python.org/3/library/os.html#os.replace).

No billing/IPAM request, WordPress write, delivery hook or provider request is retried
by this mechanism. Remote writes and lost replies keep their existing inspection and
conditional-recovery rules.

## If it still stops

An error naming changed identity fields, such as `feed changed: ctime`, is a
[metadata guard stop](windows-metadata-guards.md). It is not a rename denial and is
never retried. On the measured Windows build, the handle's `ctime` tracks metadata
change time, so equal bytes and `mtime` do not establish an unchanged owner or ACL.

1. Stop the schedule. Preserve private state, status, the candidate hash and recovery
   files. Record the exact failing phase and error code without credentials or CSV.
2. Check the destination folder's Windows permissions, available space and any process
   holding the file. A scanner is one possible cause, not proof that scanning should be
   disabled. No exclusion or security-setting change is part of this fix.
3. Inspect the current bytes and policy pair. A failure between data and policy writes
   can leave a split pair. The next run must refuse it; do not delete its marker or
   policy file to force publication.
4. After fixing the cause, use the existing [checked local recovery](local-nested-output.md)
   with the original private state and exact failed-candidate hash. In PowerShell:

```powershell
isp-geofeed-generator recover-local --config 'C:\ProgramData\ISP Geofeed Generator\config.yaml' --expected-current-sha256 COPY_FAILED_CANDIDATE_SHA256_HERE
```

Recovery does not read an input platform and does not mark publication healthy. Verify
the pair and public hosting path, then run a normal publication before resuming a timer.
An unchanged run still makes no replacement and preserves its recovery history.

To undo the code change, stop scheduling and reinstall the prior approved compatible
package. Keep state and policy files. That restores the previous immediate-failure
behavior; it does not resolve a lock or ACL problem.

## Verification scope

Tests inject transient and permanent denials, check the attempt/wait limits, verify one
prepared file, preserve a writer that acts during a wait, and exercise nested pair
failure and exact recovery. A Windows-only test holds a real file handle without delete
sharing, observes a native denial, releases it and verifies the successful retry.
These controls verify the mechanism. They do not identify a production blocking process
or guarantee that every host denial will clear within the wait budget.
