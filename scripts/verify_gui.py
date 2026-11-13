"""Native Windows Qt smoke check, using only temporary data and a memory clipboard."""
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root / ".deps"), str(root / "desktop/src")]

import ctypes
import faulthandler
import json
import os
import subprocess
from types import SimpleNamespace
import uuid

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QApplication
from clipboard_ai.gui import DockWindow, STYLE, serve_activation, socket_name
from clipboard_ai.desktop_platform import WindowsHotkeys
from clipboard_ai.instance import InstanceLock
from clipboard_ai.store import Store
from clipboard_ai.ai import AIConfig


class MemoryClipboard:
    _last = 0
    def read(self): return "Smoke test clipboard"
    def revision(self): return 0
    def changed(self): return None
    def write(self, text): pass


def main():
    if sys.platform != "win32":
        raise SystemExit("Esta comprobación nativa requiere Windows.")
    os.environ["QT_QPA_PLATFORM"] = "windows"
    faulthandler.dump_traceback_later(25)
    app = QApplication([]); app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion"); app.setStyleSheet(STYLE)
    directory = root / ".test-data" / ("gui-native-" + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    AIConfig(preload=False, autostart=False).save(directory)
    lock = InstanceLock(directory)
    assert lock.acquire()
    store = Store(directory / "dock.sqlite3")
    store.create("Prueba de la ventana\nTexto con acentos y saltos de línea. 🧪")
    store.close()
    settings = QSettings(str(directory / "desktop.ini"), QSettings.Format.IniFormat)
    for name in ("show", "send", "spelling", "image", "grammar"):
        settings.setValue("keys/" + name, "")
    settings.setValue("notifications", False)
    args = SimpleNamespace(data_dir=directory, bind="127.0.0.1", port=0, advertise=None)
    clipboard = MemoryClipboard()
    window = DockWindow(args, settings, clipboard=clipboard)
    assert window.backend.auto_receive, "El dock debe copiar lo recibido por defecto"
    print("Window constructed", flush=True)
    server = serve_activation(socket_name(directory), window)
    observed, errors = [], []
    window.backend.error.connect(errors.append)
    hotkeys = WindowsHotkeys({name: (lambda key=name: observed.append(key))
        for name in ("show", "send", "spelling", "image", "grammar")})
    app.installNativeEventFilter(hotkeys)
    registration_errors = hotkeys.configure(dict(show="Ctrl+Alt+Shift+F24", send="Ctrl+Shift+F23",
        spelling="Ctrl+Alt+Shift+F23", image="Ctrl+Alt+Shift+F22", grammar="Ctrl+Shift+F24"))
    print("Hotkey registered", registration_errors, flush=True)
    if registration_errors:
        raise RuntimeError(registration_errors)
    conflict = WindowsHotkeys(dict(show=lambda: None))
    assert conflict.configure(dict(show="Ctrl+Alt+Shift+F24")), "A conflicting shortcut must be rejected"
    client = None
    stage = 0
    result = {}
    def tick():
        nonlocal client, stage
        try:
            if errors:
                raise RuntimeError(errors)
            if stage == 0 and window.state:
                print("Worker ready", flush=True)
                window.show_window(); window.grab().save(str(directory / "dock.png"))
                cursor_screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
                assert cursor_screen.availableGeometry().contains(window.frameGeometry().center())
                screens = QGuiApplication.screens()
                if len(screens) > 1:
                    other = next((screen for screen in screens if screen is not cursor_screen), None)
                    if other:
                        window.move(other.availableGeometry().center())
                        window.show_window()
                        assert cursor_screen.availableGeometry().contains(window.frameGeometry().center())
                result.update(cursor_monitor=True, screen_count=len(screens))
                window.cursor_activity.set_state("working"); app.processEvents()
                assert window.cursor_activity.isVisible()
                window.cursor_activity.grab().save(str(directory / "cursor-working.png"))
                window.cursor_activity.set_state("copied"); app.processEvents()
                window.cursor_activity.grab().save(str(directory / "cursor-copied.png"))
                window.cursor_activity.set_state("idle")
                assert not window._expanded and window.advanced.isHidden()
                compact_size = window.size()
                window.toggle_actions()
                assert cursor_screen.availableGeometry().contains(window.frameGeometry().center())
                window.grab().save(str(directory / "dock-actions.png"))
                assert window.actions_panel.isVisible() and not window._expanded
                window.set_expanded(True)
                assert cursor_screen.availableGeometry().contains(window.frameGeometry().center())
                window.grab().save(str(directory / "dock-details-actions.png"))
                assert not window.dropzone.isVisible()
                window.set_expanded(False)
                window.toggle_actions()
                window.set_expanded(True)
                window.grab().save(str(directory / "dock-expanded.png"))
                assert window._expanded and window.history.isVisible()
                window.set_expanded(False)
                assert window.size() == compact_size
                window.hide()  # Native shortcuts must work without window focus.
                thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
                for key_id in hotkeys.registered:
                    assert ctypes.windll.user32.PostThreadMessageW(thread_id, 0x0312, key_id, 0)
                stage = 1
            elif stage == 1 and set(observed) == {"show", "send", "spelling", "image", "grammar"}:
                print("Native hotkeys received without dock focus", flush=True)
                client = subprocess.Popen([sys.executable, str(root / "scripts/run_gui.py"),
                    "--data-dir", str(directory), "--show"],
                    env=dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path[:2])))
                stage = 2
            elif stage == 2 and client.poll() is not None:
                print("Activation received", flush=True)
                assert client.returncode == 0 and window.isVisible()
                assert window.isActiveWindow(), "La segunda apertura dejó el dock detrás de otra ventana"
                result.update(native_hotkey=True, ai_hotkeys=True, shortcut_conflict=True, second_open=True,
                              compact_expand=True, tray_available=window.tray.isVisible(),
                              cursor_working_screenshot=str(directory / "cursor-working.png"),
                              cursor_copied_screenshot=str(directory / "cursor-copied.png"),
                              screenshot=str(directory / "dock.png"), expanded_screenshot=str(directory / "dock-expanded.png"))
                timer.stop(); hotkeys.close(); server.close(); window.quit_app()
        except Exception as exc:
            result["error"] = str(exc); timer.stop(); hotkeys.close(); server.close(); window.quit_app()
    def timeout():
        result["error"] = "Smoke check timed out"; timer.stop(); hotkeys.close(); server.close(); window.quit_app()
    timer = QTimer(); timer.timeout.connect(tick); timer.start(50)
    watchdog = QTimer(); watchdog.setSingleShot(True); watchdog.timeout.connect(timeout); watchdog.start(15000)
    window.backend.start(); app.exec(); watchdog.stop()
    faulthandler.cancel_dump_traceback_later()
    window.backend.stop(); window.backend.thread.join(8)
    assert not window.backend.thread.is_alive()
    lock.close()
    print(json.dumps(result, ensure_ascii=False))
    return 1 if "error" in result else 0


if __name__ == "__main__":
    raise SystemExit(main())
