"""Bounded local output reads and cooperating-writer publication protection."""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
from .client import GeofeedError
from .publish import atomic_write


@dataclass(frozen=True)
class FileState:
    data: bytes
    identity: tuple | None


def identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def read_output(path, max_bytes):
    """Do not follow final symlinks, read devices or load unbounded old files."""
    path = Path(path)
    try:
        if path.is_symlink():
            raise GeofeedError('Published output must be a regular file, not a symlink')
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise GeofeedError('Published output is not a regular file')
            data = stream.read(max_bytes + 1)
            after = os.fstat(stream.fileno())
            if len(data) > max_bytes:
                raise GeofeedError('Existing published output exceeds the supported size limit')
            if identity(before) != identity(after):
                raise GeofeedError('Published output changed during read; no partial snapshot accepted')
            return FileState(data, identity(after))
    except FileNotFoundError:
        return FileState(b'', None)
    except OSError:
        raise GeofeedError('Cannot safely read published output') from None


@contextmanager
def output_lock(path):
    """Stable sidecar inode: lock follows the destination, not a state directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(os.path.normcase(str(path.absolute())).encode()).hexdigest()
    lock_path = path.parent/('.isp-geofeed-' + key + '.lock')
    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    try:
        if lock_path.is_symlink():
            raise GeofeedError('Output lock must not be a symlink')
        fd = os.open(lock_path, flags, 0o600)
    except OSError:
        raise GeofeedError('Cannot open output lock; no write attempted') from None
    with os.fdopen(fd, 'r+b') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise GeofeedError('Output lock is not a regular file')
        try:
            if os.name == 'nt':
                import msvcrt
                if os.fstat(stream.fileno()).st_size == 0:
                    stream.write(b'0'); stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise GeofeedError('Another publisher holds the destination output lock; no write attempted') from None
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def publish_local(path, value, state_dir, backup_name, validate, max_bytes):
    target = Path(path)
    # Canonical parent aliases share a lock; retain the final component for symlink refusal.
    target = target.parent.resolve()/target.name
    with output_lock(target):
        before = read_output(target, max_bytes)
        validate(before.data, value)
        if before.data == value:
            if read_output(target, max_bytes).data != value:
                raise GeofeedError('Published output changed during unchanged-content verification; no overwrite attempted')
            return False
        atomic_write(Path(state_dir)/backup_name, before.data)

        def unchanged():
            if read_output(target, max_bytes) != before:
                raise GeofeedError('Published output changed before replacement; no overwrite attempted; recovery backup retained')

        try:
            atomic_write(target, value, 0o644, before_replace=unchanged)
        except GeofeedError:
            raise
        except OSError:
            raise GeofeedError('Local write failed; recovery needs attention. Prior bytes are in the backup; no blind restore attempted') from None
        try:
            observed = read_output(target, max_bytes)
        except GeofeedError as exc:
            raise GeofeedError(f'Local read-back failed; recovery needs attention: {exc}. Backup retained; no blind restore attempted') from None
        if observed.data != value:
            raise GeofeedError('Local read-back differs; recovery needs attention. Backup retained; refusing to overwrite a possible concurrent change')
        return True
