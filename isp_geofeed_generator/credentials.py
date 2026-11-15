"""Resolve credentials without accepting secret values in configuration or argv."""
import os
import re
import stat
from pathlib import Path
from .client import GeofeedError

NAMES = frozenset({"SONAR_API_TOKEN", "NETBOX_API_TOKEN", "WP_APP_PASSWORD",
                   "PHPIPAM_API_TOKEN",
                   "SPLYNX_API_KEY", "SPLYNX_API_SECRET", "POWERCODE_API_KEY",
                   "UISP_API_TOKEN", "VISP_CLIENT_ID", "VISP_CLIENT_SECRET", "AZOTEL_API_PASSWORD"})


def protected_file(path):
    """Accept only an owned, protected regular file. No symlinks or device reads."""
    path = Path(path)
    if not path.is_absolute():
        raise GeofeedError("Credential file paths must be absolute")
    if os.name == "nt":
        raise GeofeedError("Use Windows Credential Manager; Windows file ACL validation is not implemented")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid not in (0, os.getuid()):
                raise GeofeedError("Credential must be an owned regular file")
            if info.st_mode & (stat.S_IWGRP | stat.S_IRWXO):
                raise GeofeedError("Credential file permissions are too broad")
            if info.st_mode & stat.S_IRGRP and info.st_gid not in {os.getegid(), *os.getgroups()}:
                raise GeofeedError("Credential file group is not one of the service account's groups")
            value = stream.read(16385)
            if len(value) > 16384:
                raise GeofeedError("Credential file exceeds size limit")
            return value.decode("utf-8").rstrip("\r\n")
    except (OSError, UnicodeError):
        raise GeofeedError("Cannot read protected credential file") from None


def windows_credential(target):
    if os.name != "nt":
        raise GeofeedError("Windows Credential Manager is only available on Windows")
    import ctypes
    from ctypes import wintypes
    class Credential(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
                    ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]
    api = ctypes.WinDLL("advapi32", use_last_error=True)
    pointer = ctypes.POINTER(Credential)()
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
    api.CredReadW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    if not api.CredReadW(target, 1, 0, ctypes.byref(pointer)):
        raise GeofeedError("Windows credential entry is missing or inaccessible")
    try:
        item = pointer.contents
        if item.CredentialBlobSize > 16384:
            raise GeofeedError("Credential exceeds size limit")
        return ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize).decode("utf-16-le")
    except UnicodeError:
        raise GeofeedError("Windows credential is not UTF-16 text") from None
    finally:
        api.CredFree(pointer)


class CredentialStore:
    def __init__(self, selectors=None, environ=None):
        self.selectors = {} if selectors is None else selectors
        self.environ = os.environ if environ is None else environ
        self.backends = {}
        self._values = []
        if not isinstance(self.selectors, dict) or set(self.selectors) - NAMES:
            raise GeofeedError("Unknown credential name in credentials configuration")
        for selector in self.selectors.values():
            if not isinstance(selector, str) or not selector.startswith(("systemd:", "file:", "wincred:", "env:")):
                raise GeofeedError("Credential settings must be store references, never literal secret values")

    def get(self, name):
        if name not in NAMES:
            raise GeofeedError("Unknown credential name")
        selector = self.selectors.get(name)
        if selector is None:
            directory = self.environ.get("CREDENTIALS_DIRECTORY")
            if directory:
                # A configured systemd credential directory is authoritative.
                # Do not silently fall back to a less protected source.
                selector = "systemd:" + name
            elif self.environ.get(name + "_FILE"):
                selector = "file:" + self.environ[name + "_FILE"]
            else:
                selector = "env:" + name
        backend, argument = selector.split(":", 1)
        if not argument:
            raise GeofeedError("Empty credential-store reference")
        if backend == "systemd":
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", argument):
                raise GeofeedError("Invalid systemd credential name")
            directory = self.environ.get("CREDENTIALS_DIRECTORY")
            if not directory:
                raise GeofeedError("systemd credential directory is not available")
            value = protected_file(Path(directory) / argument)
        elif backend == "file":
            value = protected_file(argument)
        elif backend == "wincred":
            value = windows_credential(argument)
        elif backend == "env":
            if argument != name:
                raise GeofeedError("Environment credential references must use their own variable name")
            value = self.environ.get(argument, "")
        else:
            raise GeofeedError("Unsupported credential backend")
        if not value or "\n" in value or "\r" in value or "\x00" in value:
            raise GeofeedError(f"{name} is missing or invalid; no credential was reset")
        self.backends[name] = backend
        self._values.append(value)
        return value

    def redact(self, message):
        for value in sorted(set(self._values), key=len, reverse=True):
            message = message.replace(value, "[REDACTED]")
        return message
