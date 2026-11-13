"""Native Windows clipboard; Linux commands are selected at runtime."""
import ctypes
import os
import shutil
import subprocess
import sys
import time


class Clipboard:
    def __init__(self):
        if sys.platform == "win32":
            from ctypes import wintypes
            self.user = ctypes.WinDLL("user32", use_last_error=True)
            self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            self.user.OpenClipboard.argtypes = [wintypes.HWND]
            self.user.GetClipboardData.argtypes = [wintypes.UINT]
            self.user.GetClipboardData.restype = wintypes.HANDLE
            self.user.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
            self.user.SetClipboardData.restype = wintypes.HANDLE
            self.kernel.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
            self.kernel.GlobalAlloc.restype = wintypes.HGLOBAL
            self.kernel.GlobalLock.argtypes = [wintypes.HGLOBAL]
            self.kernel.GlobalLock.restype = ctypes.c_void_p
            self.kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
            self.kernel.GlobalFree.argtypes = [wintypes.HGLOBAL]
            self._window = None
            self.user.CreateWindowExW.restype = wintypes.HWND
            self.user.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
        elif sys.platform == "darwin":
            self.read_command, self.write_command = ["pbpaste"], ["pbcopy"]
        elif os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste") and shutil.which("wl-copy"):
            self.read_command, self.write_command = ["wl-paste", "--no-newline"], ["wl-copy"]
        elif shutil.which("xclip"):
            self.read_command = ["xclip", "-selection", "clipboard", "-o"]
            self.write_command = ["xclip", "-selection", "clipboard", "-i"]
        else:
            raise RuntimeError("Linux requiere wl-clipboard (Wayland) o xclip (X11)")
        self._last = self.revision()

    def _open(self, writing=False):
        if writing and not self._window:
            self._window = self.user.CreateWindowExW(0, "STATIC", "Clipboard AI", 0,
                                                     0, 0, 0, 0, None, None, None, None)
            if not self._window:
                raise OSError("No se pudo crear el propietario del portapapeles")
        for _ in range(5):
            if self.user.OpenClipboard(self._window if writing else None):
                return
            time.sleep(0.01)
        raise OSError("El portapapeles está ocupado; vuelve a intentarlo")

    def read(self):
        if sys.platform != "win32":
            return subprocess.run(self.read_command, capture_output=True, check=True, timeout=2).stdout.decode("utf-8")
        self._open()
        try:
            handle = self.user.GetClipboardData(13)
            if not handle:
                return ""
            pointer = self.kernel.GlobalLock(handle)
            if not pointer:
                raise OSError("No se pudo leer el portapapeles")
            try:
                return ctypes.wstring_at(pointer)
            finally:
                self.kernel.GlobalUnlock(handle)
        finally:
            self.user.CloseClipboard()

    def write(self, text):
        if "\0" in text:
            raise ValueError("El portapapeles de texto no admite caracteres NUL")
        if sys.platform != "win32":
            subprocess.run(self.write_command, input=text.encode("utf-8"), check=True, timeout=2)
        else:
            data = (text + "\0").encode("utf-16-le")
            handle = self.kernel.GlobalAlloc(0x0042, len(data))
            if not handle:
                raise OSError("No se pudo reservar memoria para el portapapeles")
            transferred = False
            try:
                pointer = self.kernel.GlobalLock(handle)
                if not pointer:
                    raise OSError("No se pudo acceder a la memoria del portapapeles")
                ctypes.memmove(pointer, data, len(data))
                self.kernel.GlobalUnlock(handle)
                self._open(writing=True)
                try:
                    if not self.user.EmptyClipboard() or not self.user.SetClipboardData(13, handle):
                        raise OSError("No se pudo escribir en el portapapeles")
                    transferred = True
                finally:
                    self.user.CloseClipboard()
            finally:
                if not transferred:
                    self.kernel.GlobalFree(handle)
        self._last = self.revision()

    def revision(self):
        if sys.platform == "win32":
            return self.user.GetClipboardSequenceNumber()
        return self.read()

    def changed(self):
        revision = self.revision()
        if revision == self._last:
            return None
        text = self.read()
        self._last = revision
        return text or None
