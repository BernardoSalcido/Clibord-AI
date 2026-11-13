"""Desktop integration, isolated from the network and storage."""
import ctypes
import os
import plistlib
from pathlib import Path
import subprocess
import sys

from PySide6.QtCore import QAbstractNativeEventFilter


def parse_hotkey(text):
    parts = text.replace(" ", "").upper().split("+")
    mods = 0
    for part in parts[:-1]:
        if part not in {"ALT", "CTRL", "SHIFT", "META", "WIN"}:
            raise ValueError("Usa Ctrl, Alt, Shift o Meta y una letra, número o tecla F.")
        mods |= {"ALT": 1, "CTRL": 2, "SHIFT": 4, "META": 8, "WIN": 8}[part]
    key = parts[-1]
    if len(key) == 1 and key.isascii() and key.isalnum():
        vk = ord(key)
    elif key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError("El atajo debe terminar en una letra, número o tecla F1–F24.")
    if not mods:
        raise ValueError("El atajo necesita al menos Ctrl, Alt, Shift o Meta.")
    return mods | 0x4000, vk  # MOD_NOREPEAT


def is_copy_hotkey(text):
    """A global Ctrl+C registration would prevent other apps from copying."""
    try:
        return parse_hotkey(text) == parse_hotkey("Ctrl+C")
    except (ValueError, IndexError):
        return False


def shortcut_released(text):
    """Wait for the physical global shortcut before injecting a plain Ctrl+C."""
    if os.name != "nt":
        return True
    _, vk = parse_hotkey(text)
    keys = [vk, 0x10, 0x11, 0x12, 0x5B, 0x5C]  # Key, Shift, Ctrl, Alt, Win
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user.GetAsyncKeyState.restype = ctypes.c_short
    return all(not (user.GetAsyncKeyState(key) & 0x8000) for key in keys)


def copy_focused_selection():
    """Send Ctrl+C to the foreground application without activating the dock."""
    if os.name != "nt":
        return False
    class KeyInput(ctypes.Structure):
        _fields_ = [("vk", ctypes.c_ushort), ("scan", ctypes.c_ushort),
                    ("flags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                    ("extra", ctypes.c_size_t)]

    class MouseInput(ctypes.Structure):
        _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                    ("mouse_data", ctypes.c_ulong), ("flags", ctypes.c_ulong),
                    ("time", ctypes.c_ulong), ("extra", ctypes.c_size_t)]

    class InputUnion(ctypes.Union):
        _fields_ = [("keyboard", KeyInput), ("mouse", MouseInput)]

    class Input(ctypes.Structure):
        _anonymous_ = ("data",)
        _fields_ = [("type", ctypes.c_ulong), ("data", InputUnion)]

    keys = (Input * 4)(
        Input(1, InputUnion(keyboard=KeyInput(0x11, 0, 0, 0, 0))),
        Input(1, InputUnion(keyboard=KeyInput(0x43, 0, 0, 0, 0))),
        Input(1, InputUnion(keyboard=KeyInput(0x43, 0, 2, 0, 0))),
        Input(1, InputUnion(keyboard=KeyInput(0x11, 0, 2, 0, 0))),
    )
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(Input), ctypes.c_int]
    user.SendInput.restype = ctypes.c_uint
    return user.SendInput(4, keys, ctypes.sizeof(Input)) == 4


class WindowsHotkeys(QAbstractNativeEventFilter):
    def __init__(self, callbacks):
        super().__init__()
        self.callbacks = callbacks
        self.registered = {}
        self.user = ctypes.WinDLL("user32", use_last_error=True) if os.name == "nt" else None

    def configure(self, bindings):
        self.close()
        errors = []
        if not self.user:
            return errors
        assigned = {parse_hotkey(value) for value in bindings.values() if value}
        for index, (name, text) in enumerate(bindings.items()):
            if not text:
                continue
            try:
                mods, vk = parse_hotkey(text)
                key_id = 0x4340 + index
                if not self.user.RegisterHotKey(None, key_id, mods, vk):
                    raise ValueError(f"{text}: otro programa lo utiliza o Windows lo reserva")
                self.registered[key_id] = name
                # Shift produces a capital letter on many keyboard layouts. Accept
                # either physical spelling unless that combination was explicitly
                # assigned to a different action.
                if 0x41 <= vk <= 0x5A and not mods & 4 and (mods | 4, vk) not in assigned:
                    shifted_id = 0x4440 + index
                    if not self.user.RegisterHotKey(None, shifted_id, mods | 4, vk):
                        raise ValueError(f"{text} con Mayús: otro programa lo utiliza")
                    self.registered[shifted_id] = name
            except ValueError as exc:
                errors.append(str(exc))
        return errors

    def nativeEventFilter(self, event_type, message):
        if self.user:
            from ctypes.wintypes import MSG
            msg = MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam in self.registered:
                self.callbacks[self.registered[msg.wParam]]()
                return True, 0
        return False, 0

    def close(self):
        if self.user:
            for key_id in self.registered:
                self.user.UnregisterHotKey(None, key_id)
        self.registered.clear()


def startup_command(arguments):
    executable = Path(sys.executable)
    windowed = executable.with_name("pythonw.exe")
    if windowed.exists():
        executable = windowed
    launcher = Path(__file__).resolve().parents[3] / "scripts" / "run_gui.py"
    target = [str(executable), str(launcher)] if launcher.exists() else [str(executable), "-m", "clipboard_ai.gui"]
    return subprocess.list2cmdline(target + list(arguments))


def startup_enabled():
    if sys.platform == "darwin":
        return _mac_startup_file().is_file()
    if os.name != "nt":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            winreg.QueryValueEx(key, "ClipboardAI")
        return True
    except FileNotFoundError:
        return False


def migrate_hidden_startup(arguments):
    """Upgrade this installation's old Run entry to open the dock visibly."""
    if os.name != "nt":
        return False
    import winreg
    expected = startup_command(arguments)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
        try:
            current, _ = winreg.QueryValueEx(key, "ClipboardAI")
        except FileNotFoundError:
            return False
        if current != expected + " --background":
            return False
        winreg.SetValueEx(key, "ClipboardAI", 0, winreg.REG_SZ, expected)
        return True


def set_startup(enabled, arguments):
    if sys.platform == "darwin":
        path = _mac_startup_file()
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            launcher = Path(__file__).resolve().parents[3] / "scripts" / "run_gui.py"
            command = ([str(Path(sys.executable)), str(launcher)] if launcher.exists() else
                       [str(Path(sys.executable)), "-m", "clipboard_ai.gui"])
            data = dict(Label="org.clipboardai.dock", ProgramArguments=command + list(arguments),
                        RunAtLoad=True, KeepAlive=False)
            temporary = path.with_suffix(".tmp")
            with temporary.open("wb") as stream:
                plistlib.dump(data, stream)
            temporary.replace(path)
        else:
            path.unlink(missing_ok=True)
        return
    if os.name != "nt":
        raise OSError("El inicio automático de esta entrega está disponible en Windows.")
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
        if enabled:
            winreg.SetValueEx(key, "ClipboardAI", 0, winreg.REG_SZ, startup_command(arguments))
        else:
            try:
                winreg.DeleteValue(key, "ClipboardAI")
            except FileNotFoundError:
                pass


def _mac_startup_file():
    return Path.home() / "Library" / "LaunchAgents" / "org.clipboardai.dock.plist"
