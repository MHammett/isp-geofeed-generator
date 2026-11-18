# Windows metadata guard stops

The local publisher keeps a strict identity guard. It checks bytes, device, file ID,
size, modification time (`mtime`) and `ctime`. Any change stops publication. There is
no metadata-only exception, waiting for the change to disappear, or automatic retry
of a failed guard. This policy also applies during checked recovery.

Errors identify the component and fixed field names, for example
`[feed changed: ctime]` or `[policy changed: content,file_id]`. Read-time failures can
report `[changed: ctime]`. They do not print contents, paths, IDs or timestamp values.
These details describe what differed; they do not identify the process responsible.

This is separate from the [bounded rename retry](windows-file-writes.md). That retry
handles selected Windows errors from `os.replace`. A changed identity stops before
another rename attempt. It is not treated as a sharing denial.

## What the Windows timestamp means

On the measured Python 3.12.10 workstation, handle-based `os.fstat` exposed native
Windows `ChangeTime` as `st_ctime_ns`. It was distinct from creation time. A path-based
`os.stat` call on that build used creation time for `st_ctime_ns` instead. Do not use
the path call's meaning to interpret the guard's handle call.

The [CPython implementation](https://github.com/python/cpython/blob/v3.12.10/Python/fileutils.c)
maps the native change time through its handle read. The
[upstream issue](https://github.com/python/cpython/issues/157671) records the differing
path/handle behavior. Python marks Windows `st_ctime` as deprecated in
[its reference](https://docs.python.org/3.12/library/os.html#os.stat_result).
These are version-specific facts, not a promise about every Python/filesystem pair.

[Microsoft distinguishes](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_basic_info)
data modification time from metadata change time. Attribute, permission or other
metadata changes can matter even when bytes and `mtime` match. Equal bytes alone
are not grounds to ignore a changed identity. An owner or ACL change may be a real
security event.

## Evidence from issue 88

On 2026-11-18, a local 369-test run recorded two stops in unchanged publication code.
An isolated temporary diagnostic reproduced one stop with equal bytes, device,
file ID, size and `mtime`, but a changed `ctime`. The actor was not captured.
[Issue #88](https://github.com/MHammett/isp-geofeed-generator/issues/88) holds that
evidence and remains open.

Later native probes matched `fstat` to Windows change time. Twenty-four fresh-file
samples and twenty-four same-name samples did not reproduce spontaneous drift.
A separate twelve-file experiment deliberately made access time two hours old:
reading updated access time without changing metadata change time. That rules out
ordinary access updates in that experiment, not every possible outside actor.
The workstation's access-time policy was read without changing it. A volume-info
read was denied and did not establish volume configuration.

[Claude's independent measurements](https://github.com/MHammett/isp-geofeed-generator/issues/88#issuecomment-6985512669)
confirmed the path/handle difference on Python 3.12.10 and 3.13.12. He did not catch an
actor in 160 fresh files either. His measurements support the timestamp distinction;
agreement about a scanner or indexer would not prove the cause.

## Regression and recovery controls

The Windows-only controls use fresh disposable files. One sets and clears their
read-only attribute. Another changes DACL protection, verifies that real change,
and restores the original protection and exact DACL bytes. Neither changes a
workstation setting or a production ACL. Both must preserve bytes, file ID, size and
`mtime` while producing a measured `ctime` change.

The first hosted ACL trial changed protection but observed the same timestamp. It
failed its precondition rather than counting the control as exercised. The fixture
now waits 50 ms before the deliberate mutation to separate it from the preceding
rename. It still requires an actual timestamp change. This is test setup, not a
production wait, retry or acceptance rule. Timestamp resolution can vary by host.

Both trials stop after writing the candidate and before replacing the old policy.
The candidate, old policy and exact backup must remain. Ordinary publication must
refuse that split pair. After restoring test-only security metadata, explicit
hash-bound recovery must restore the original bytes and policy. A private module
copy that removes `ctime` must fail a separate assertion, with intact code passing
before and after. Other controls reject changed contents, every identity field,
same-byte replacement and a different policy owner.

A later local 377-test run passed with two POSIX-only skips. That pass does not erase
the earlier stop or prove the outside change harmless. The new diagnostics and
controls do not claim to eliminate intermittent Windows stops.

## If a scheduled run stops

Stop the schedule and retain the failed status, candidate hash and private recovery
files. Inspect the named feed or policy component and its permissions. Identify the
process that changed metadata using a scoped operating-system trace if needed;
such a trace has not yet identified this workstation's actor.

Follow [checked local recovery](local-nested-output.md) after inspection. Do not
delete a policy marker, edit a transaction hash, disable a scanner, change global
access-time settings or broaden ACLs to make the guard pass. A different owner's
bytes or policy must remain protected. Verify the restored pair and public hosting
path, then require a normal verified publication before resuming the schedule.

To undo the diagnostic change, reinstall the prior approved compatible package while
keeping the state and sidecars. The identity rule is the same in both versions.
No merge, workstation setting change or production deployment is part of this work.
