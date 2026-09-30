"""Per-user Windows instance guard and window activation signal."""

import ctypes
from ctypes import wintypes
import getpass
import hashlib


class WindowsInstance:
    def __init__(self, name=None):
        if name is None:
            user = hashlib.sha256(getpass.getuser().encode('utf-8')).hexdigest()
            name = 'Local\\productivity-tool-dictation-' + user
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateEventW.restype = wintypes.HANDLE
        self.kernel.SetEvent.argtypes = [wintypes.HANDLE]
        self.kernel.SetEvent.restype = wintypes.BOOL
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.event = None
        self.mutex = None
        try:
            self.event = self.kernel.CreateEventW(None, False, False, name + '-activate')
            if not self.event:
                raise ctypes.WinError(ctypes.get_last_error())
            self.mutex = self.kernel.CreateMutexW(None, False, name)
            error = ctypes.get_last_error()
            if not self.mutex:
                raise ctypes.WinError(error)
            self.primary = error != 183
            if not self.primary and not self.kernel.SetEvent(self.event):
                raise ctypes.WinError(ctypes.get_last_error())
        except OSError:
            self.close()
            raise

    def activation_requested(self):
        result = self.kernel.WaitForSingleObject(self.event, 0)
        if result == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        return result == 0

    def close(self):
        for attribute in ('mutex', 'event'):
            handle = getattr(self, attribute)
            if handle:
                self.kernel.CloseHandle(handle)
                setattr(self, attribute, None)