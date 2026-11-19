"""Create a new, restricted evidence directory without changing existing ACLs."""
import os
from pathlib import Path
from .client import GeofeedError


def _windows_create(path):
    import ctypes as c
    from ctypes import wintypes as w
    kernel = c.WinDLL('kernel32', use_last_error=True)
    api = c.WinDLL('advapi32', use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes = [c.c_void_p]
    api.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]
    api.GetTokenInformation.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
    api.ConvertSidToStringSidW.argtypes = [c.c_void_p, c.POINTER(c.c_void_p)]
    api.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, c.POINTER(c.c_void_p), c.c_void_p]
    class Attributes(c.Structure):
        _fields_ = [('length', w.DWORD), ('descriptor', c.c_void_p), ('inherit', w.BOOL)]
    kernel.CreateDirectoryW.argtypes = [w.LPCWSTR, c.POINTER(Attributes)]
    token, sid_text, descriptor = w.HANDLE(), c.c_void_p(), c.c_void_p()
    try:
        if not api.OpenProcessToken(kernel.GetCurrentProcess(), 8, c.byref(token)):
            raise OSError()
        size = w.DWORD()
        api.GetTokenInformation(token, 1, None, 0, c.byref(size))
        buffer = c.create_string_buffer(size.value)
        if not api.GetTokenInformation(token, 1, buffer, size.value, c.byref(size)):
            raise OSError()
        sid = c.cast(buffer, c.POINTER(c.c_void_p))[0]
        if not api.ConvertSidToStringSidW(sid, c.byref(sid_text)):
            raise OSError()
        # Protected DACL, inherited by files: current user and SYSTEM only.
        sddl = 'D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;' + c.wstring_at(sid_text) + ')'
        if not api.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, c.byref(descriptor), None):
            raise OSError()
        attributes = Attributes(c.sizeof(Attributes), descriptor, False)
        if not kernel.CreateDirectoryW(str(path), c.byref(attributes)):
            raise OSError()
    finally:
        if descriptor: kernel.LocalFree(descriptor)
        if sid_text: kernel.LocalFree(sid_text)
        if token: kernel.CloseHandle(token)


def create_directory(path):
    path = Path(path).absolute()
    try:
        if os.name == 'nt':
            _windows_create(path)
        elif os.name == 'posix':
            path.mkdir(mode=0o700)  # Exclusive; parent must already exist.
        else:
            raise OSError()
    except OSError:
        raise GeofeedError('Capture needs a new restricted directory with an existing parent; existing destinations are never overwritten or resumed, no request made') from None
    return path


def write_new(path, data):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
    with os.fdopen(os.open(path, flags, 0o600), 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
