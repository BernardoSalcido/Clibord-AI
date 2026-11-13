"""Headless UI and real TLS-worker checks, isolated from the user's clipboard/data."""
import asyncio
import copy
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
pytest.importorskip("PySide6")
from PySide6.QtCore import QObject, QSettings, QMimeData, QPoint, QPointF, QRect, QUrl, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QDrag, QDropEvent, QGuiApplication, QKeySequence
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QKeySequenceEdit, QMessageBox, QSystemTrayIcon
from websockets.asyncio.client import connect

from clipboard_ai.gui import AISettingsDialog, DockWindow, PairDialog, serve_activation, socket_name
from clipboard_ai.gui_backend import Backend, QtClipboard, export_copy
from clipboard_ai.desktop_platform import is_copy_hotkey, parse_hotkey, startup_command
from clipboard_ai.instance import InstanceLock
from clipboard_ai.files import CHUNK, FileDock
from clipboard_ai.protocol import decode, encode
from clipboard_ai.ai import AIConfig
from clipboard_ai.store import Store


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    return application


def pump(app, predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while not predicate():
        app.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("Qt/worker condition timed out")
        time.sleep(0.01)
    app.processEvents()


class FakeBackend(QObject):
    snapshot = Signal(object)
    completed = Signal(str, object)
    error = Signal(str)
    notice = Signal(str)
    stopped = Signal()
    ai_activity = Signal(str)
    accepting = True

    def __init__(self):
        super().__init__()
        self.requests = []
        self.stop_called = False

    def request(self, action, *args):
        self.requests.append((action, args))

    def stop(self):
        self.stop_called = True


class MemoryClipboard:
    def __init__(self, text="clipboard sample"):
        self.text = text
        self._last = 0
        self._revision = 0
        self._lock = threading.Lock()
        self.writes = []
        self.images = []
        self.events = []

    def read(self): return self.text
    def revision(self):
        with self._lock: return self._revision
    def changed(self): return None
    def write(self, text, expected_revision=None):
        with self._lock:
            if expected_revision is not None and self._revision != expected_revision:
                return False
            self.text = text; self._revision += 1
            self.writes.append(text); self.events.append(("text", text))
            return True

    def write_image(self, path):
        image = Path(path).read_bytes()
        with self._lock:
            self.text = ""; self._revision += 1
            self.images.append(image); self.events.append(("image", image))
            return True

    def external_copy(self, text):
        with self._lock:
            self.text = text; self._revision += 1


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    from clipboard_ai.gui import WindowsHotkeys
    monkeypatch.setattr(WindowsHotkeys, "configure", lambda self, bindings: [])
    backend = FakeBackend()
    args = SimpleNamespace(data_dir=tmp_path, bind="127.0.0.1", port=0, advertise=None)
    widget = DockWindow(args, QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat), backend, MemoryClipboard())
    yield widget
    widget.hotkeys.close(); widget.tray.hide(); widget.cursor_activity.set_state("idle")
    widget.cursor_activity.close(); widget.hide(); widget.deleteLater(); app.processEvents()


def test_cursor_badge_shows_real_ai_outcome_without_taking_input(window, app):
    badge = window.cursor_activity
    window.backend.ai_activity.emit("working"); app.processEvents()
    assert badge.state == "working" and badge.isVisible() and badge.tick.isActive()
    assert bool(badge.windowFlags() & Qt.WindowType.WindowTransparentForInput)
    assert badge.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    window.backend.ai_activity.emit("copied"); app.processEvents()
    assert badge.state == "copied" and badge.dismiss.isActive()
    window.backend.ai_activity.emit("working"); app.processEvents()
    assert badge.state == "working" and not badge.dismiss.isActive()
    window.backend.ai_activity.emit("saved"); app.processEvents()
    assert badge.state == "saved" and badge.LABELS[badge.state] == "No copiado"
    window.backend.ai_activity.emit("error"); app.processEvents()
    assert badge.state == "error"
    badge.dismiss.timeout.emit(); app.processEvents()
    assert badge.state == "idle" and not badge.isVisible() and not badge.tick.isActive()


def state(directory):
    return dict(texts=[dict(id="text-id", origin="remote", seq=1, created="2026-10-16T10:00:00", text="Español 🧪\n dos líneas", delivered=1)],
        files=[dict(id="file-id", item=dict(name="paper.pdf", size=100, mime="application/pdf", created="2026-10-16T11:00:00"),
                    direction="in", state="receiving", offset=40, path=str(directory / "paper.pdf"), error="")],
        peers=[dict(id="peer", name="OnePlus")], device="local", connected=True, paused=False,
        auto_send=False, auto_receive=False, pending_text=0, pending_files=1,
        used=100, delivered=(0, 0), inbox=str(directory), received=str(directory), port=45821)


def test_history_filters_progress_text_copy_and_live_automatic_controls(window, tmp_path):
    snapshot = state(tmp_path)
    window.update_state(snapshot)
    window.set_expanded(True)
    assert window.history.count() == 1
    window.sections.setCurrentIndex(2)
    assert window.progress.value() == 40
    assert window.delete_button.text() == "Cancelar"
    window.sections.setCurrentIndex(0); window.search.setText("español")
    assert window.history.count() == 1
    assert window.detail_body.toPlainText() == "Español 🧪\n dos líneas"
    window.copy_button.click()
    assert window.backend.requests[-1] == ("copy", ("text-id",))
    window.auto_receive.click()
    assert window.backend.requests[-1] == ("automatic", (True, True))
    window.result("automatic", (True, True))
    assert window.settings.value("automatic/send", type=bool)
    window.search.clear(); window.sections.setCurrentIndex(2)
    assert window.history.count() == 1
    snapshot = copy.deepcopy(snapshot)
    snapshot["files"][0]["state"] = "delivered"
    snapshot["files"][0]["offset"] = 100
    window.update_state(snapshot)
    assert window.progress.value() == 100
    assert not window.open_button.isHidden()
    window.sections.setCurrentIndex(0); window.search.setText("missing")
    assert window.history.count() == 0
    assert window.detail_body.toPlainText() == ""


def test_compact_default_expand_collapse_and_restart(window, app):
    window.update_state(state(window.args.data_dir))
    window.show(); app.processEvents()
    assert not window._expanded and window.advanced.isHidden()
    assert window.dropzone.isVisible() and window.clip_button.isVisible()
    assert not window.file_button.isVisible() and not window.history.isVisible()
    assert window.height() < 500
    window.clip_button.click()
    assert window.backend.requests[-1] == ("clip", ())
    compact_size = window.size()
    window.expand_button.click(); app.processEvents()
    assert window._expanded and window.file_button.isVisible() and window.history.isVisible()
    assert window.height() > compact_size.height()
    window.expand_button.click(); app.processEvents()
    assert not window._expanded and window.size() == compact_size
    window.focus_search(); app.processEvents()
    assert window._expanded and window.search.hasFocus()
    window.save_window_geometry()
    # Even an expanded last session reopens as a small dock.
    restored = DockWindow(window.args, window.settings, FakeBackend(), MemoryClipboard())
    try:
        restored.show(); app.processEvents()
        assert not restored._expanded and not restored.history.isVisible()
        assert restored.height() < 500
    finally:
        restored.hotkeys.close(); restored.tray.hide(); restored.cursor_activity.close()
        restored.hide(); restored.deleteLater()


def test_resizable_panels_survive_collapse_and_restart(window, app, tmp_path):
    window.update_state(state(tmp_path))
    window.show(); window.set_expanded(True); window.toggle_actions()
    window.resize(1450, 900); app.processEvents()
    window.content_splitter.setSizes([1030, 320])
    window.history_splitter.setSizes([350, 620])
    window.vertical_splitter.setSizes([410, 170])
    app.processEvents()
    window.save_window_geometry(); window.settings.sync()
    expected = (window.content_splitter.sizes(), window.history_splitter.sizes(),
                window.vertical_splitter.sizes())
    assert expected[0][1] > 280  # The action panel actually grows past its default.
    window.set_expanded(False); app.processEvents()
    window.set_expanded(True); app.processEvents()
    for before, after in zip(expected, (window.content_splitter.sizes(),
            window.history_splitter.sizes(), window.vertical_splitter.sizes())):
        assert abs(before[0] / sum(before) - after[0] / sum(after)) < 0.03
    restored = DockWindow(window.args,
        QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat),
        FakeBackend(), MemoryClipboard())
    try:
        restored.update_state(state(tmp_path))
        restored.show(); restored.set_expanded(True); restored.toggle_actions()
        app.processEvents()
        for before, after in zip(expected, (restored.content_splitter.sizes(),
                restored.history_splitter.sizes(), restored.vertical_splitter.sizes())):
            assert abs(before[0] / sum(before) - after[0] / sum(after)) < 0.03
    finally:
        restored.hotkeys.close(); restored.tray.hide(); restored.cursor_activity.close()
        restored.hide(); restored.deleteLater()


def test_history_sections_keep_images_text_and_documents_separate(window, tmp_path):
    snapshot = state(tmp_path)
    picture = copy.deepcopy(snapshot["files"][0])
    picture["id"] = "picture-id"; picture["item"]["name"] = "screenshot.png"
    picture["item"]["mime"] = "image/png"
    snapshot["files"].append(picture)
    window.update_state(snapshot)
    assert window.history.count() == 1 and window.selected()["kind"] == "text"
    window.sections.setCurrentIndex(1)
    assert window.history.count() == 1 and window.selected()["id"] == "picture-id"
    assert "Imagen" in window.history.item(0).text()
    window.sections.setCurrentIndex(2)
    assert window.history.count() == 1 and window.selected()["id"] == "file-id"
    assert [window.sections.tabText(index) for index in range(3)] == ["Textos (1)", "Imágenes (1)", "Archivos (1)"]


def test_english_navigation_keeps_ai_mode_and_history(window, tmp_path):
    window.update_state(state(tmp_path))
    window.spelling_mode.setChecked(True)
    window.language = "en"
    window.apply_language()
    assert window.settings_button.text() == "Settings"
    assert window.sections.tabText(0) == "Texts (1)"
    assert window.correction_level.currentData() == "spelling"
    assert window.correction_level.itemText(1) == "Medium · spelling"


@pytest.mark.parametrize("language,tabs,save", [
    ("es", ("Imagen → Texto", "Media · Ortografía", "Alta · Gramática"), "Guardar"),
    ("en", ("Image → Text", "Medium · Spelling", "High · Grammar"), "Save"),
])
def test_ai_settings_uses_current_language_and_correction_levels(window, language, tabs, save):
    window.language = language
    dialog = AISettingsDialog(window)
    try:
        assert tuple(dialog.tabs.tabText(i) for i in range(3)) == tabs
        assert dialog.editors["spelling"].toPlainText() == window.ai_config.prompts["spelling"]
        assert dialog.editors["grammar"].toPlainText() == window.ai_config.prompts["grammar"]
        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons.button(QDialogButtonBox.StandardButton.Save).text() == save
    finally:
        dialog.close()


def test_screenshot_is_saved_even_when_ocr_toggle_is_off(window):
    source = dict(revision=7, text="", image=b"image bytes")
    assert not window.ai_config.image
    assert window.clipboard_bridge.capture_image is True
    window.external_clipboard_changed(source)
    assert window.backend.requests == [("capture_image_local", (source["image"],))]
    window.image_mode.setChecked(True)
    window.backend.requests.clear()
    window.external_clipboard_changed(source)
    assert [action for action, _ in window.backend.requests] == ["capture_image_local", "ai_submit"]
    assert window.backend.requests[-1][1] == (source,)
    window.backend.requests.clear()
    window.external_clipboard_changed(dict(revision=8, text="Normal Ctrl+C", image=None))
    assert window.backend.requests == []


def test_capture_without_ai_reaches_images_tab_and_survives_restart(app, tmp_path, monkeypatch):
    import base64
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    from clipboard_ai.gui import WindowsHotkeys
    monkeypatch.setattr(WindowsHotkeys, "configure", lambda self, bindings: [])
    config = AIConfig(preload=False, autostart=False, image=False, text_mode="none")
    config.save(tmp_path)
    args = SimpleNamespace(data_dir=tmp_path, bind="127.0.0.1", port=0, advertise=None)
    clipboard = MemoryClipboard()
    backend = Backend(args, clipboard, ai_config=config)
    window = DockWindow(args, QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat), backend, clipboard)
    picture = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==")
    errors = []
    backend.error.connect(errors.append)
    backend.start()
    try:
        pump(app, lambda: backend.accepting)
        window.external_clipboard_changed(dict(revision=1, text="", image=picture))
        pump(app, lambda: bool(window.state and window.state["files"]))
        assert not errors
        assert window.state["texts"] == []
        assert (window.state["files"][0]["direction"], window.state["files"][0]["state"]) == ("local", "delivered")
        window.sections.setCurrentIndex(1)
        assert window.history.count() == 1
        assert window.selected()["row"]["item"]["mime"] == "image/png"
        assert Path(window.selected()["row"]["path"]).read_bytes() == picture
        window.external_clipboard_changed(dict(revision=2, text="Copiado con Ctrl+C", image=None))
        app.processEvents()
        assert window.state["texts"] == []
        window._copy_send_armed = True
        window._copy_send_revision = 2
        window.external_clipboard_changed(dict(revision=3, text="Copiado con Ctrl+Alt+C", image=None))
        pump(app, lambda: bool(window.state["texts"]))
        assert window.state["texts"][0]["text"] == "Copiado con Ctrl+Alt+C"
        assert window.state["texts"][0]["delivered"] == 0  # Queued while phone is offline.
    finally:
        backend.stop(); backend.thread.join(5)
        window.hotkeys.close(); window.tray.hide(); window.cursor_activity.close(); window.hide()
        assert not backend.thread.is_alive()


def test_open_dock_moves_from_stale_monitor_to_cursor_monitor(window, app, monkeypatch):
    class Screen:
        def availableGeometry(self): return QRect(1920, 0, 1920, 1080)
    monkeypatch.setattr(QGuiApplication, "screenAt", lambda position: Screen())
    monkeypatch.setattr(QCursor, "pos", lambda: QPoint(2000, 100))
    window.move(100, 100)
    window.show_window(); app.processEvents()
    assert 1920 <= window.x() <= 3840 - window.width()
    assert 0 <= window.y() <= 1080 - window.height()
    first = window.pos()
    window.show_window(); app.processEvents()
    assert window.pos() == first


def test_close_to_tray_keeps_worker_and_no_tray_exit_stops_it(window, app, monkeypatch):
    window.show(); app.processEvents()
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    monkeypatch.setattr(window.tray, "isVisible", lambda: True)
    monkeypatch.setattr(window.tray, "showMessage", lambda *args: None)
    window.close()
    assert not window.isVisible() and not window.backend.stop_called
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.show(); window.close()
    assert window.backend.stop_called


def test_pair_qr_expiry_and_close_remove_payload(window, app):
    dialog = PairDialog(window); dialog.show()
    payload = json.dumps(dict(v=1, host="192.168.1.2", port=45821, fingerprint="a" * 64, code="temporary"))
    dialog.show_payload(payload)
    assert dialog.svg.renderer().isValid()
    assert dialog.payload.toPlainText() == payload
    dialog.seconds = 0; dialog.tick()
    assert not dialog.payload.toPlainText()
    assert dialog.svg.isHidden()
    dialog.close(); app.processEvents()
    assert window.backend.requests[-1][0] == "close_pair"


def test_file_drop_forces_copy_and_local_socket_activates_existing(window, app, tmp_path):
    path = tmp_path / "original.txt"; path.write_text("keep")
    mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(str(path))])
    event = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction | Qt.DropAction.MoveAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    received = []; window.dropzone.files_dropped.connect(received.append)
    window.dropzone.dropEvent(event)
    assert [[Path(item) for item in group] for group in received] == [[path]]
    assert event.dropAction() == Qt.DropAction.CopyAction
    assert path.read_text() == "keep"
    name = socket_name(tmp_path)
    server = serve_activation(name, window)
    try:
        code = "import sys; from clipboard_ai.gui import activate_existing; sys.exit(0 if activate_existing(sys.argv[1],sys.argv[2]) else 1)"
        client = subprocess.Popen([sys.executable, "-c", code, name, "show"])
        pump(app, lambda: client.poll() is not None)
        assert client.returncode == 0
        pump(app, window.isVisible)
        client = subprocess.Popen([sys.executable, "-c", code, name, "send"])
        pump(app, lambda: client.poll() is not None)
        assert client.returncode == 0
        pump(app, lambda: any(action == "clip" for action, args in window.backend.requests))
    finally:
        server.close()


def test_instance_lock_releases_and_export_preserves_source(tmp_path):
    first = InstanceLock(tmp_path); second = InstanceLock(tmp_path)
    assert first.acquire()
    assert not second.acquire()
    first.close()
    assert second.acquire(); second.close()
    source = tmp_path / "source.bin"; source.write_bytes(bytes(range(256)))
    target = tmp_path / "export.bin"
    export_copy(source, target)
    assert source.read_bytes() == target.read_bytes()
    with pytest.raises(ValueError):
        export_copy(source, source)
    assert not list(tmp_path.glob("*.tmp"))


def test_hotkey_validation_and_quoted_startup_command():
    assert parse_hotkey("Ctrl+Alt+D") == (0x4003, ord("D"))
    assert is_copy_hotkey("Ctrl+C") and not is_copy_hotkey("Ctrl+Alt+C")
    assert parse_hotkey("Ctrl+Shift+F12") == (0x4006, 0x7B)
    for value in ("A", "Ctrl+", "Ctrl+Space", "Ctrl+A, Ctrl+B", "Ctrl+F25"):
        with pytest.raises(ValueError):
            parse_hotkey(value)
    command = startup_command(["--data-dir", "C:/test path/data"])
    assert '"C:/test path/data"' in command and "--background" not in command


def test_windows_copy_injection_uses_plain_ctrl_c_without_touching_real_keyboard(monkeypatch):
    import clipboard_ai.desktop_platform as platform
    recorded = []
    class FakeSendInput:
        def __call__(self, count, inputs, size):
            recorded.append((count, size, [(item.keyboard.vk, item.keyboard.flags) for item in inputs]))
            return count
    monkeypatch.setattr(platform.ctypes, "WinDLL", lambda *args, **kwargs:
                        SimpleNamespace(SendInput=FakeSendInput()))
    assert platform.copy_focused_selection()
    assert recorded[0][0] == 4
    assert recorded[0][2] == [(0x11, 0), (ord("C"), 0), (ord("C"), 2), (0x11, 2)]
    assert recorded[0][1] == 40  # Native 64-bit INPUT structure required by SendInput.


def test_global_letter_hotkey_accepts_shifted_capital_without_stealing_explicit_binding():
    from clipboard_ai.desktop_platform import WindowsHotkeys
    registered = []
    class FakeUser:
        def RegisterHotKey(self, handle, key_id, mods, vk):
            registered.append((mods, vk)); return True
        def UnregisterHotKey(self, handle, key_id): return True
    hotkeys = WindowsHotkeys(dict(send=lambda: None, grammar=lambda: None))
    hotkeys.user = FakeUser()
    assert not hotkeys.configure(dict(send="ctrl+alt+c", grammar="Ctrl+Alt+Shift+G"))
    assert (0x4003, ord("C")) in registered
    assert (0x4007, ord("C")) in registered
    assert registered.count((0x4007, ord("G"))) == 1
    hotkeys.close()


def test_send_shortcut_defaults_to_ctrl_alt_c_and_ctrl_c_remains_reserved(window):
    window.settings.setValue("keys/send", "Ctrl+C")
    assert window.bindings() == dict(show="Ctrl+Alt+D", send="Ctrl+Alt+C", spelling="Ctrl+Alt+O",
                                   image="Ctrl+Alt+I", grammar="Ctrl+Alt+G")
    assert window.configure_hotkeys(dict(show="Ctrl+C"))


def test_send_shortcut_can_be_edited_and_persisted_in_settings(window, monkeypatch):
    import clipboard_ai.gui as gui
    monkeypatch.setattr(gui, "startup_enabled", lambda: False)
    monkeypatch.setattr(gui, "set_startup", lambda *args: None)
    def edit_and_save(dialog):
        editors = dialog.findChildren(QKeySequenceEdit)
        assert len(editors) == 5
        assert editors[0].objectName() == "hotkey_send"
        assert editors[0].keySequence().toString() == "Ctrl+Alt+C"
        editors[0].setKeySequence(QKeySequence("Ctrl+Alt+V"))
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
        return 0
    monkeypatch.setattr(QDialog, "exec", edit_and_save)
    window.show_settings()
    assert window.bindings()["send"] == "Ctrl+Alt+V"


def test_legacy_send_default_migrates_once_and_remains_editable(window):
    window.settings.remove("keys/copy_send_default_migrated")
    window.settings.setValue("keys/send", "ctrl+alt+s")
    assert window.bindings()["send"] == "Ctrl+Alt+C"
    window.settings.setValue("keys/send", "Ctrl+Alt+S")
    assert window.bindings()["send"] == "Ctrl+Alt+S"


@pytest.mark.parametrize("mode", ["spelling", "grammar", "image"])
def test_copy_and_send_routes_new_content_to_selected_ai_action(window, mode):
    from dataclasses import replace
    window.ai_config = replace(window.ai_config, image=mode == "image",
                               text_mode=mode if mode != "image" else "none")
    window._copy_send_armed = True
    window._copy_send_revision = 3
    source = dict(revision=4, text="Texto seleccionado" if mode != "image" else "",
                  image=b"image data" if mode == "image" else None)
    window.external_clipboard_changed(source)
    assert [action for action, _ in window.backend.requests] == [
        "capture_image" if mode == "image" else "clipboard_text", "ai_submit"]
    assert window.backend.requests[-1][1] == (source,)


@pytest.mark.parametrize("mode", ["spelling", "grammar"])
def test_normal_copy_does_not_submit_to_ai(window, mode):
    from dataclasses import replace
    window.ai_config = replace(window.ai_config, text_mode=mode)
    window.external_clipboard_changed(dict(revision=1, text="Copia normal", image=None))
    assert window.backend.requests == []


def test_explorer_image_is_sent_as_file_and_processed_only_on_explicit_copy(window, tmp_path):
    from dataclasses import replace
    path = tmp_path / "imagen.png"
    picture = QImage(40, 40, QImage.Format.Format_RGB32); picture.fill(QColor("white"))
    assert picture.save(str(path))
    window.ai_config = replace(window.ai_config, image=True)
    source = dict(revision=1, text="", image=None, files=[str(path)])
    window.external_clipboard_changed(source)
    assert window.backend.requests == []
    window._copy_send_revision = 0; window._copy_send_armed = True
    window.external_clipboard_changed(source)
    assert window.backend.requests[0] == ("files", ([str(path)],))
    assert window.backend.requests[1][0] == "ai_submit"
    assert window.backend.requests[1][1][0]["image"].startswith(b"\x89PNG")


def test_global_ai_hotkey_callbacks_toggle_modes_independent_of_dock_focus(window, tmp_path, monkeypatch):
    import clipboard_ai.gui as gui
    copied = []
    monkeypatch.setattr(gui, "shortcut_released", lambda binding: True)
    monkeypatch.setattr(gui, "copy_focused_selection", lambda: copied.append(True) or True)
    window.update_state(state(tmp_path))
    assert parse_hotkey("cTrL+aLt+o") == parse_hotkey("Ctrl+Alt+O")
    window.hide()
    window.hotkey_callbacks["spelling"]()
    assert window.ai_config.text_mode == "spelling"
    window.hotkey_callbacks["grammar"]()
    assert window.ai_config.text_mode == "grammar" and not window.spelling_mode.isChecked()
    window.hotkey_callbacks["grammar"]()
    assert window.ai_config.text_mode == "none"
    window.hotkey_callbacks["image"]()
    assert window.ai_config.image
    before = list(window.backend.requests)
    window.hotkey_callbacks["send"]()
    assert copied and window.backend.requests == before
    window.external_clipboard_changed(dict(revision=1, text="Selección nueva", image=None))
    assert window.backend.requests[-1] == ("clipboard_text", ("Selección nueva",))
    assert window.configure_hotkeys(dict(show="Ctrl+Alt+O", spelling="ctrl+alt+o"))


def test_copy_and_send_never_sends_stale_clipboard_and_uses_edited_binding(window, monkeypatch):
    import clipboard_ai.gui as gui
    bindings = []
    monkeypatch.setattr(gui, "shortcut_released", lambda binding: bindings.append(binding) or True)
    monkeypatch.setattr(gui, "copy_focused_selection", lambda: True)
    window.settings.setValue("keys/send", "cTrL+aLt+v")
    window.copy_and_send()
    assert bindings == ["cTrL+aLt+v"]
    assert window.backend.requests == []
    window._copy_send_timed_out(window._copy_send_id)
    assert window.backend.requests == [] and not window._copy_send_armed
    window.copy_and_send()
    window.external_clipboard_changed(dict(revision=window._copy_send_revision + 1,
                                           text="Nuevo", image=None))
    assert window.backend.requests == [("clipboard_text", ("Nuevo",))]


def test_successive_send_notifications_are_grouped_and_counted(window, tmp_path, monkeypatch):
    messages = []
    monkeypatch.setattr(window.tray, "isVisible", lambda: True)
    monkeypatch.setattr(window.tray, "showMessage", lambda *args: messages.append(args))
    baseline = state(tmp_path)
    window.update_state(baseline)
    for index in range(3):
        snapshot = copy.deepcopy(baseline)
        snapshot["texts"].extend(dict(snapshot["texts"][0], id=f"sent-{number}",
            origin="local") for number in range(index + 1))
        window.update_state(snapshot)
        baseline = snapshot
    window.flush_notifications()
    assert len(messages) == 1
    assert "Enviados al dock: 3 (3 textos)" in messages[0][1]
    window.update_state(baseline)
    window.flush_notifications()
    assert len(messages) == 1
    window.settings.setValue("notifications", False)
    snapshot = copy.deepcopy(baseline)
    snapshot["texts"].append(dict(snapshot["texts"][0], id="sent-again", origin="local"))
    window.update_state(snapshot)
    window.flush_notifications()
    assert len(messages) == 1


def test_mixed_media_and_receipts_use_one_counted_notification(window, tmp_path, monkeypatch):
    messages = []
    monkeypatch.setattr(window.tray, "isVisible", lambda: True)
    monkeypatch.setattr(window.tray, "showMessage", lambda *args: messages.append(args))
    baseline = state(tmp_path)
    window.update_state(baseline)
    snapshot = copy.deepcopy(baseline)
    snapshot["files"][0]["state"] = "delivered"
    snapshot["files"].extend([
        dict(snapshot["files"][0], id="sent-image", direction="out", state="pending",
             item=dict(snapshot["files"][0]["item"], name="capture.png", mime="image/png")),
        dict(snapshot["files"][0], id="sent-file", direction="out", state="pending")])
    snapshot["texts"].append(dict(snapshot["texts"][0], id="received-text"))
    window.update_state(snapshot)
    window.flush_notifications()
    assert len(messages) == 1
    assert "Enviados al dock: 2 (1 imagen, 1 archivo)" in messages[0][1]
    assert "Recibidos: 2 (1 texto, 1 archivo)" in messages[0][1]


def test_image_preview_and_drag_export_preserve_original(window, app, tmp_path, monkeypatch):
    picture = tmp_path / "internal.blob"
    image = QImage(80, 40, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    assert image.save(str(picture), "PNG")
    snapshot = state(tmp_path)
    snapshot["files"] = [dict(id="image-id", item=dict(name="Captura.png", size=picture.stat().st_size,
        mime="image/png", created="2026-10-16T11:00:00"), direction="in", state="delivered",
        offset=picture.stat().st_size, path=str(picture), error="")]
    window.update_state(snapshot)
    window.set_expanded(True)
    window.show(); app.processEvents()
    window.sections.setCurrentIndex(1)
    pump(app, lambda: bool(window.preview_label.pixmap()))
    assert window.preview_label.isVisible()
    assert not window.history.item(0).icon().isNull()
    exports = window.prepare_drag_files([window.selected()])
    assert len(exports) == 1 and exports[0].name.endswith("Captura.png")
    assert exports[0].read_bytes() == picture.read_bytes()
    exports[0].write_bytes(b"changed")
    assert picture.read_bytes() != b"changed"
    offered = []
    def inspect_drag(drag, *args):
        data = drag.mimeData()
        offered.append((data.hasUrls(), data.hasImage(), Path(data.urls()[0].toLocalFile()).name))
        return Qt.DropAction.CopyAction
    monkeypatch.setattr(QDrag, "exec", inspect_drag)
    window.history.startDrag(Qt.DropAction.CopyAction)
    assert offered == [(True, True, "Captura.png")]


def test_pending_text_can_be_removed_from_expanded_history(window, tmp_path, monkeypatch):
    snapshot = state(tmp_path)
    snapshot["texts"] = [dict(snapshot["texts"][0], origin="local", delivered=0)]
    window.update_state(snapshot)
    window.set_expanded(True)
    assert window.delete_button.text() == "Cancelar y eliminar"
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.delete_button.click()
    assert window.backend.requests[-1] == ("delete_text", ("text-id",))
    snapshot = copy.deepcopy(snapshot); snapshot["texts"] = []
    window.update_state(snapshot)
    assert window.history.count() == 0


class FakeQtClipboard(QObject):
    dataChanged = Signal()

    def __init__(self):
        super().__init__(); self.value = "original"

    def text(self): return self.value
    def setText(self, value):
        self.value = value; self.dataChanged.emit()


def test_qt_clipboard_cross_thread_and_echo_suppression(app):
    clipboard = FakeQtClipboard(); bridge = QtClipboard(clipboard)
    errors = []
    def write():
        try: bridge.write("received á🧪")
        except Exception as exc: errors.append(exc)
    thread = threading.Thread(target=write); thread.start()
    pump(app, lambda: not thread.is_alive()); thread.join()
    assert not errors and clipboard.text() == "received á🧪"
    assert bridge.changed() is None
    clipboard.setText("manually copied")
    assert bridge.changed() == "manually copied"
    assert bridge.changed() is None


def test_received_image_is_written_on_qt_thread_without_being_published_again(app, tmp_path):
    class ImageClipboard(QObject):
        dataChanged = Signal()

        def __init__(self):
            super().__init__()
            self.mime = QMimeData(); self.mime.setText("original")

        def text(self): return self.mime.text()
        def mimeData(self): return self.mime
        def image(self):
            value = self.mime.imageData()
            return value if isinstance(value, QImage) else QImage()
        def setMimeData(self, value):
            self.mime = value; self.dataChanged.emit()
            QTimer.singleShot(40, self.dataChanged.emit)

    picture = QImage(20, 12, QImage.Format.Format_RGB32); picture.fill(QColor("blue"))
    path = tmp_path / "phone.png"
    assert picture.save(str(path), "PNG")
    clipboard = ImageClipboard(); bridge = QtClipboard(clipboard); published = []
    bridge.external_changed.connect(published.append)
    errors = []

    def copy():
        try: bridge.write_image(path)
        except Exception as exc: errors.append(exc)

    thread = threading.Thread(target=copy); thread.start()
    pump(app, lambda: not thread.is_alive()); thread.join()
    assert not errors and clipboard.image().size() == picture.size()
    assert bridge.changed() is None
    image_revision = bridge.revision()
    deadline = time.monotonic() + .2
    while time.monotonic() < deadline: app.processEvents(); time.sleep(.01)
    assert not published and bridge.revision() == image_revision
    request = dict(text="Markdown", expected_revision=image_revision,
                   done=threading.Event(), error=None, written=False)
    bridge._write(request)
    assert request["written"] and clipboard.text() == "Markdown"
    bridge.write_ui("newer text")
    assert clipboard.text() == "newer text" and bridge.changed() is None
    bridge.capture_timer.stop()


def test_ai_capture_image_text_own_writes_and_atomic_clipboard_guard(app):
    class RichClipboard(FakeQtClipboard):
        picture = None
        files = False
        def mimeData(self):
            mime = QMimeData()
            if self.files:
                mime.setUrls([QUrl.fromLocalFile("C:/documents/paper.pdf")]); return mime
            if self.picture is not None: mime.setImageData(self.picture)
            return mime
        def image(self): return self.picture
        def setText(self, value):
            self.picture = None
            super().setText(value)
    clipboard = RichClipboard(); bridge = QtClipboard(clipboard); observed = []
    bridge.external_changed.connect(observed.append)
    clipboard.setText("one"); clipboard.setText("two")
    pump(app, lambda: len(observed) == 1)
    assert observed[0]["text"] == "two"
    previous = bridge.revision()
    clipboard.setText("new user input")
    request = dict(text="stale AI", expected_revision=previous, done=threading.Event(), error=None, written=False)
    bridge._write(request)
    assert not request["written"] and clipboard.text() == "new user input"
    bridge.write_ui("own result")
    deadline = time.monotonic() + .2
    while time.monotonic() < deadline: app.processEvents(); time.sleep(.01)
    assert len(observed) == 1
    cancelled = threading.Event(); cancelled.set()
    request = dict(text="cancelled", expected_revision=bridge.revision(), cancel_event=cancelled,
                   done=threading.Event(), error=None, written=False)
    bridge._write(request)
    assert clipboard.text() == "own result"
    clipboard.picture = QImage(20, 20, QImage.Format.Format_RGB32); clipboard.picture.fill(QColor("white"))
    clipboard.dataChanged.emit()
    pump(app, lambda: len(observed) == 2)
    assert observed[-1]["image"].startswith(b"\x89PNG")
    clipboard.files = True; clipboard.picture = None; clipboard.value = "C:/documents/paper.pdf"
    clipboard.dataChanged.emit()
    deadline = time.monotonic() + .2
    while time.monotonic() < deadline: app.processEvents(); time.sleep(.01)
    assert len(observed) == 3 and clipboard.value == "C:/documents/paper.pdf"
    assert observed[-1]["files"] == ["C:/documents/paper.pdf"]


def test_explicit_copy_accepts_identical_image_again(app):
    class ImageClipboard(QObject):
        dataChanged = Signal()
        def __init__(self):
            super().__init__()
            self.picture = QImage(20, 20, QImage.Format.Format_RGB32)
            self.picture.fill(QColor("blue"))
        def text(self): return ""
        def mimeData(self):
            mime = QMimeData(); mime.setImageData(self.picture); return mime
        def image(self): return self.picture
    clipboard = ImageClipboard(); sequence = [1]
    bridge = QtClipboard(clipboard, sequence=lambda: sequence[0]); events = []
    bridge.external_changed.connect(events.append)
    sequence[0] += 1; clipboard.dataChanged.emit()
    pump(app, lambda: len(events) == 1)
    bridge.prepare_explicit_copy()
    sequence[0] += 1; clipboard.dataChanged.emit()
    pump(app, lambda: len(events) == 2)
    assert events[1]["revision"] > events[0]["revision"]


def test_ai_actions_independent_panels_persist_and_text_modes_exclusive(window, app):
    window.update_state(state(window.args.data_dir)); window.show(); app.processEvents()
    window.actions_button.click(); app.processEvents()
    assert window.actions_panel.isVisible() and not window._expanded
    window.image_mode.click(); window.grammar_mode.click()
    assert window.ai_config.image and window.ai_config.text_mode == "grammar"
    window.spelling_mode.click()
    assert window.ai_config.text_mode == "spelling" and not window.grammar_mode.isChecked()
    window.set_expanded(True); app.processEvents()
    assert window.actions_panel.isVisible() and not window.dropzone.isVisible()
    window.actions_button.click(); app.processEvents()
    assert window._expanded and not window.actions_panel.isVisible()
    from clipboard_ai.ai import AIConfig
    restored = AIConfig.load(window.args.data_dir)
    assert restored.image and restored.text_mode == "spelling"


def test_delayed_and_reformatted_own_clipboard_notifications_do_not_trigger_ai(app):
    class DelayedClipboard(QObject):
        dataChanged = Signal()
        def __init__(self):
            super().__init__(); self.mime = QMimeData(); self.mime.setText("initial")
        def text(self): return self.mime.text()
        def mimeData(self): return self.mime
        def setMimeData(self, mime):
            self.mime = mime
            # Windows notifies after the application has returned from its own write.
            QTimer.singleShot(20, self.dataChanged.emit)
            QTimer.singleShot(170, self.dataChanged.emit)
        def external(self, value):
            self.mime = QMimeData(); self.mime.setText(value); self.dataChanged.emit()
    clipboard = DelayedClipboard(); bridge = QtClipboard(clipboard); events = []
    bridge.external_changed.connect(events.append)
    clipboard.external("source"); pump(app, lambda: len(events) == 1)
    source_revision = bridge.revision()
    clipboard.dataChanged.emit(); clipboard.dataChanged.emit()
    assert bridge.revision() == source_revision
    bridge.write_ui("Corrected\ntext")
    # A clipboard manager strips the private MIME marker, converts LF to CRLF and adds HTML.
    def reformat():
        clipboard.external("Corrected\r\ntext"); clipboard.mime.setHtml("<p>Corrected text</p>")
        clipboard.dataChanged.emit()
    QTimer.singleShot(250, reformat)
    deadline = time.monotonic() + .6
    while time.monotonic() < deadline: app.processEvents(); time.sleep(.01)
    assert len(events) == 1 and bridge.changed() is None
    # A genuinely different copy re-arms processing, and a later intentional re-copy works.
    clipboard.external("different"); pump(app, lambda: len(events) == 2)
    clipboard.external("Corrected\ntext"); pump(app, lambda: len(events) == 3)


def test_windows_sequence_poll_detects_keyboard_copy_and_delayed_text_without_qt_event(app):
    clipboard = FakeQtClipboard(); sequence = [1]
    bridge = QtClipboard(clipboard, sequence=lambda: sequence[0]); events = []
    bridge.external_changed.connect(events.append)
    try:
        clipboard.value = "Copied with Ctrl+C"; sequence[0] += 1
        pump(app, lambda: len(events) == 1)
        assert events[0]["text"] == "Copied with Ctrl+C"
        # Ctrl+C may publish its sequence first, then render UnicodeText later without another event.
        clipboard.value = ""; sequence[0] += 1; bridge._poll()
        QTimer.singleShot(150, lambda: setattr(clipboard, "value", "Delayed keyboard copy"))
        pump(app, lambda: len(events) == 2)
        assert events[-1]["text"] == "Delayed keyboard copy"
        # Check the native counter again before committing an AI result.
        expected = bridge.revision(); clipboard.value = "newer"; sequence[0] += 1
        request = dict(text="stale", expected_revision=expected, done=threading.Event(), error=None, written=False)
        bridge._write(request)
        assert not request["written"] and clipboard.text() == "newer"
    finally:
        bridge.poll_timer.stop(); bridge.capture_timer.stop()


def test_repeated_keyboard_copy_is_a_new_input_but_duplicate_format_is_not(app):
    clipboard = FakeQtClipboard(); sequence = [1]
    bridge = QtClipboard(clipboard, sequence=lambda: sequence[0]); events = []
    clipboard.owner_id = 41
    bridge.owner = lambda: clipboard.owner_id
    bridge.external_changed.connect(events.append)
    try:
        clipboard.value = "same text"; sequence[0] += 1
        pump(app, lambda: len(events) == 1)
        clipboard.dataChanged.emit()
        app.processEvents()
        assert len(events) == 1
        clipboard.owner_id = 42  # Clipboard manager republishes the same text.
        sequence[0] += 1
        app.processEvents()
        assert len(events) == 1
        clipboard.owner_id = 41
        sequence[0] += 1  # Ctrl+C copied the same selection again.
        pump(app, lambda: len(events) == 2)
        bridge.capture_text = False
        bridge.capture_text = True; bridge.rearm()
        clipboard.dataChanged.emit()  # Also allow the first copy after enabling a mode.
        pump(app, lambda: len(events) == 3)
    finally:
        bridge.poll_timer.stop(); bridge.capture_timer.stop()


def test_failed_clipboard_setter_is_not_reported_as_copied(app):
    class FailedClipboard(FakeQtClipboard):
        def setMimeData(self, mime):
            pass
    clipboard = FailedClipboard(); bridge = QtClipboard(clipboard)
    request = dict(text="AI result", done=threading.Event(), error=None, written=False)
    bridge._write(request)
    assert request["error"] and not request["written"]
    assert clipboard.text() == "original"
    bridge.capture_timer.stop()


@pytest.mark.parametrize("raw_png", [False, True])
def test_screenshot_pixels_take_priority_over_file_url_and_duplicate_formats(app, raw_png):
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice
    class ScreenshotClipboard(FakeQtClipboard):
        def __init__(self):
            super().__init__(); self.picture = QImage(30, 20, QImage.Format.Format_RGB32)
            self.picture.fill(QColor("white")); self.is_picture = True
        def mimeData(self):
            mime = QMimeData()
            if self.is_picture:
                mime.setUrls([QUrl.fromLocalFile("C:/Pictures/Screenshots/capture.png")])
                if raw_png:
                    data = QByteArray(); buffer = QBuffer(data); buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                    self.picture.save(buffer, "PNG"); mime.setData("image/png", data)
                else: mime.setImageData(self.picture)
            return mime
        def image(self): return QImage() if raw_png else self.picture
        def setText(self, value):
            self.is_picture = False; super().setText(value)
    clipboard = ScreenshotClipboard(); bridge = QtClipboard(clipboard); events = []
    bridge.external_changed.connect(events.append)
    clipboard.dataChanged.emit(); pump(app, lambda: len(events) == 1)
    original = events[0]
    # Snipping Tool publishes more image formats while OCR is already running.
    clipboard.dataChanged.emit()
    deadline = time.monotonic() + .2
    while time.monotonic() < deadline: app.processEvents(); time.sleep(.01)
    assert len(events) == 1
    assert bridge.revision() != original["revision"]
    request = dict(text="OCR result", expected_revision=original["revision"], expected_image=original["image"],
                   done=threading.Event(), error=None, written=False)
    bridge._write(request)
    assert request["written"] and clipboard.text() == "OCR result"
    clipboard.is_picture = True; clipboard.picture.fill(QColor("red")); clipboard.dataChanged.emit()
    # A genuinely different screenshot must never be replaced by the old result.
    request = dict(text="old OCR", expected_revision=original["revision"], expected_image=original["image"],
                   done=threading.Event(), error=None, written=False)
    bridge._write(request)
    assert not request["written"]


def test_worker_preserves_pairing_tls_files_pause_restart_and_settings(app, tmp_path):
    peer = str(uuid.uuid4())
    store = Store(tmp_path / "dock.sqlite3")
    token = store.pair(peer, "OnePlus")
    previous = store.create("existing text")
    store.close()
    args = SimpleNamespace(data_dir=tmp_path, bind="127.0.0.1", port=0, advertise=None)
    backend = Backend(args, MemoryClipboard(), True, True)
    snapshots, results, errors, stopped = [], [], [], []
    backend.snapshot.connect(snapshots.append)
    backend.completed.connect(lambda action, value: results.append((action, value)))
    backend.error.connect(errors.append); backend.stopped.connect(lambda: stopped.append(True))
    backend.start()
    try:
        pump(app, lambda: bool(snapshots) or bool(errors))
        assert not errors
        snapshot = snapshots[-1]
        assert snapshot["peers"][0]["name"] == "OnePlus"
        assert snapshot["texts"][0]["id"] == previous["id"]
        assert snapshot["auto_send"] and snapshot["auto_receive"]
        port = snapshot["port"]
        source = tmp_path / "binary.bin"; source.write_bytes(bytes(range(256)) * 700)
        backend.request("files", [str(source)])
        pump(app, lambda: any(action == "files" for action, _ in results))
        assert not errors
        trusted = ssl.create_default_context(cafile=str(tmp_path / "server.pem")); trusted.check_hostname = False

        async def scenario():
            async with connect(f"wss://127.0.0.1:{port}", ssl=trusted, proxy=None) as ws:
                await ws.send(encode("hello", device=peer, token=token, capabilities=["files-v1"]))
                assert decode(await ws.recv())["type"] == "welcome"
                assert decode(await ws.recv())["item"] == previous
                assert decode(await ws.recv())["type"] == "ready"
                await ws.send(encode("ack", id=previous["id"]))
                await ws.send(encode("ready"))
                offer = decode(await ws.recv())
                assert offer["type"] == "file_offer"
                # Receive through a second real FileDock, so all chunk/hash checks run.
                receiver = FileDock(tmp_path / "phone", peer)
                try:
                    msg = receiver.handle(offer, backend._last_snapshot["device"])
                    while msg["type"] != "file_done":
                        await ws.send(json.dumps(msg))
                        incoming = decode(await ws.recv())
                        msg = receiver.handle(incoming, backend._last_snapshot["device"])
                    await ws.send(json.dumps(msg))
                    row = receiver.history()[0]
                    assert Path(row["path"]).read_bytes() == source.read_bytes()
                    backend.request("send", "desktop UI → Android 🧪")
                    # A duplicate offer may be queued after file_done; consume it safely.
                    while True:
                        outgoing = decode(await ws.recv())
                        if outgoing["type"] == "item":
                            break
                    assert outgoing["item"]["text"] == "desktop UI → Android 🧪"
                    await ws.send(encode("ack", id=outgoing["item"]["id"]))
                    incoming = dict(id=str(uuid.uuid4()), origin=peer, seq=1, created="now", text="phone → UI")
                    await ws.send(encode("item", item=incoming, live=True))
                    while decode(await ws.recv())["type"] != "ack":
                        pass
                finally:
                    receiver.close()
        asyncio.run(asyncio.wait_for(scenario(), 15))
        pump(app, lambda: any(row["text"] == "phone → UI" for row in snapshots[-1]["texts"]))
        assert backend.clipboard.writes == ["phone → UI"]
        backend.request("pause")
        pump(app, lambda: snapshots[-1]["paused"])
        assert not snapshots[-1]["connected"]
        backend.request("send", "offline pending")
        pump(app, lambda: any(row["text"] == "offline pending" for row in snapshots[-1]["texts"]))
        backend.request("pause")
        pump(app, lambda: not snapshots[-1]["paused"])
        assert not errors
    finally:
        backend.stop(); pump(app, lambda: bool(stopped)); backend.thread.join(3)
    assert not backend.thread.is_alive()
    reopened = Store(tmp_path / "dock.sqlite3")
    assert reopened.authenticate(peer, token)
    assert any(item["text"] == "offline pending" for item in reopened.pending())
    reopened.close()


def test_copied_text_and_capture_arrive_over_existing_tls_protocol(app, tmp_path):
    import base64
    peer = str(uuid.uuid4())
    store = Store(tmp_path / "dock.sqlite3")
    token = store.pair(peer, "Android")
    store.close()
    args = SimpleNamespace(data_dir=tmp_path, bind="127.0.0.1", port=0, advertise=None)
    backend = Backend(args, MemoryClipboard(), True, False)
    snapshots, errors = [], []
    backend.snapshot.connect(snapshots.append); backend.error.connect(errors.append)
    backend.start()
    picture = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==")
    try:
        pump(app, lambda: bool(snapshots) or bool(errors))
        assert not errors
        trusted = ssl.create_default_context(cafile=str(tmp_path / "server.pem")); trusted.check_hostname = False

        async def scenario():
            async with connect(f"wss://127.0.0.1:{snapshots[-1]['port']}", ssl=trusted, proxy=None) as ws:
                await ws.send(encode("hello", device=peer, token=token, capabilities=["files-v1"]))
                assert decode(await ws.recv())["type"] == "welcome"
                assert decode(await ws.recv())["type"] == "ready"
                await ws.send(encode("ready"))
                backend.request("capture_image", picture)
                offer = decode(await ws.recv())
                assert offer["type"] == "file_offer" and offer["file"]["mime"] == "image/png"
                receiver = FileDock(tmp_path / "phone", peer)
                try:
                    reply = receiver.handle(offer, backend.store.device)
                    while reply["type"] != "file_done":
                        await ws.send(json.dumps(reply))
                        reply = receiver.handle(decode(await ws.recv()), backend.store.device)
                    await ws.send(json.dumps(reply))
                    assert Path(receiver.history()[0]["path"]).read_bytes() == picture
                    backend.request("clipboard_text", "Selección enviada")
                    while True:
                        message = decode(await ws.recv())
                        if message["type"] == "item": break
                    assert message["live"] is True and message["item"]["text"] == "Selección enviada"
                    await ws.send(encode("ack", id=message["item"]["id"]))
                finally:
                    receiver.close()
        asyncio.run(asyncio.wait_for(scenario(), 15))
        assert not errors
    finally:
        backend.stop(); backend.thread.join(5)
        assert not backend.thread.is_alive()


@pytest.mark.parametrize("copy_during_processing", [False, True])
def test_phone_image_is_processed_by_brain_and_result_returns_over_tls(app, tmp_path, monkeypatch,
                                                                        copy_during_processing):
    import base64
    import clipboard_ai.gui_backend as backend_module
    started, proceed = threading.Event(), threading.Event()

    class FakeAI:
        def __init__(self, config, status=None):
            self.config = config
        async def prepare(self, *args): pass
        async def process(self, mode, text, image):
            if mode == "image":
                assert image.startswith(b"\x89PNG")
                started.set()
                if copy_during_processing:
                    assert await asyncio.to_thread(proceed.wait, 5)
                return "$$\nx^2\n$$", {"input_tokens": 1}
            assert mode == "grammar" and text == "teh" and image is None
            return "the", {"input_tokens": 1}
        async def close(self): pass

    monkeypatch.setattr(backend_module, "LocalAI", FakeAI)
    peer = str(uuid.uuid4())
    store = Store(tmp_path / "dock.sqlite3")
    token = store.pair(peer, "OnePlus")
    store.close()
    args = SimpleNamespace(data_dir=tmp_path, bind="127.0.0.1", port=0, advertise=None)
    backend = Backend(args, MemoryClipboard(), True, True, AIConfig(preload=False, image=True))
    snapshots, errors, activity = [], [], []
    backend.snapshot.connect(snapshots.append); backend.error.connect(errors.append)
    backend.ai_activity.connect(activity.append)
    backend.start()
    picture = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==")
    try:
        pump(app, lambda: bool(snapshots) or bool(errors))
        assert not errors
        trusted = ssl.create_default_context(cafile=str(tmp_path / "server.pem")); trusted.check_hostname = False

        async def scenario():
            sender = FileDock(tmp_path / "phone", peer)
            source = tmp_path / "capture.png"; source.write_bytes(picture)
            uploaded = sender.add(source)
            try:
                async with connect(f"wss://127.0.0.1:{snapshots[-1]['port']}", ssl=trusted, proxy=None) as ws:
                    await ws.send(encode("hello", device=peer, token=token, capabilities=["files-v1", "hub-v2"]))
                    assert decode(await ws.recv())["type"] == "welcome"
                    assert decode(await ws.recv())["type"] == "settings"
                    assert decode(await ws.recv())["type"] == "ready"
                    await ws.send(encode("ready"))
                    offer = sender.offers()[0]
                    await ws.send(json.dumps(offer))
                    while True:
                        message = decode(await ws.recv())
                        if message["type"] == "item":
                            assert message["item"]["text"] == "$$\nx^2\n$$"
                            assert message["result"] == dict(source_id=uploaded["id"],
                                                              action="image", source_origin=peer)
                            await ws.send(encode("ack", id=message["item"]["id"]))
                            break
                        if message["type"].startswith("file_"):
                            reply = sender.handle(message, backend.store.device)
                            if reply:
                                await ws.send(json.dumps(reply))
                            if message["type"] == "file_done" and copy_during_processing:
                                assert await asyncio.to_thread(started.wait, 5)
                                backend.clipboard.external_copy("copia posterior")
                                proceed.set()
                    await ws.send(json.dumps(offer))
                    while decode(await ws.recv())["type"] != "file_done":
                        pass
                    prompts = dict(image="OCR preciso", spelling="Ortografía mínima", grammar="Gramática mínima")
                    await ws.send(encode("settings_update", base_revision=0,
                                         changes=dict(text_mode="grammar", prompts=prompts)))
                    while True:
                        message = decode(await ws.recv())
                        if message["type"] == "settings" and message["revision"] == 1:
                            assert message["values"]["prompts"] == prompts
                            break
                    entry = dict(id=str(uuid.uuid4()), origin=peer, seq=1, created="now", text="teh")
                    await ws.send(encode("item", item=entry, live=True))
                    while True:
                        message = decode(await ws.recv())
                        if message["type"] == "item" and message.get("result", {}).get("action") == "grammar":
                            assert message["item"]["text"] == "the"
                            assert message["result"]["source_id"] == entry["id"]
                            break
            finally:
                sender.close()
        asyncio.run(asyncio.wait_for(scenario(), 12))
        assert not errors
        assert backend.clipboard.images == [picture]
        expected = ["teh"] if copy_during_processing else ["$$\nx^2\n$$", "teh"]
        assert backend.clipboard.writes == expected
        expected_events = [("image", picture)] + [("text", text) for text in expected]
        assert backend.clipboard.events == expected_events
        pump(app, lambda: ("saved" if copy_during_processing else "copied") in activity)
        assert "working" in activity
    finally:
        proceed.set()
        backend.stop(); backend.thread.join(5)
        assert not backend.thread.is_alive()


def test_worker_quit_immediately_after_start_is_safe(app, tmp_path):
    args = SimpleNamespace(data_dir=tmp_path, bind="127.0.0.1", port=0, advertise=None)
    backend = Backend(args, MemoryClipboard())
    stopped, errors = [], []
    backend.stopped.connect(lambda: stopped.append(True)); backend.error.connect(errors.append)
    backend.start(); backend.stop()
    pump(app, lambda: bool(stopped)); backend.thread.join(3)
    assert not errors and not backend.thread.is_alive()


@pytest.mark.parametrize("watched", [False, True])
def test_quit_during_copy_commits_accepted_file(app, tmp_path, monkeypatch, watched):
    started, release = threading.Event(), threading.Event()
    original = FileDock.prepare
    def slow_prepare(self, source, signature=None):
        started.set()
        if not release.wait(6):
            raise RuntimeError("Test did not release importer")
        return original(self, source, signature)
    monkeypatch.setattr(FileDock, "prepare", slow_prepare)
    args = SimpleNamespace(data_dir=tmp_path, bind="127.0.0.1", port=0, advertise=None)
    backend = Backend(args, MemoryClipboard())
    snapshots, errors, stopped = [], [], []
    backend.snapshot.connect(snapshots.append); backend.error.connect(errors.append)
    backend.stopped.connect(lambda: stopped.append(True))
    backend.start()
    try:
        pump(app, lambda: bool(snapshots))
        path = Path(snapshots[-1]["inbox"]) / "watched.bin" if watched else tmp_path / "manual.bin"
        path.write_bytes(b"preserve pending data" * CHUNK)
        if not watched:
            backend.request("files", [str(path)])
        pump(app, started.is_set)
        backend.stop()
        app.processEvents()
        assert backend.thread.is_alive()
        release.set(); pump(app, lambda: bool(stopped))
    finally:
        release.set(); backend.stop(); backend.thread.join(8)
    assert not errors and not backend.thread.is_alive()
    store = Store(tmp_path / "dock.sqlite3")
    dock = FileDock(tmp_path / "Dock", store.device)
    assert len(dock.history()) == 1
    row = dock.history()[0]
    assert row["state"] == "pending" and Path(row["path"]).read_bytes() == path.read_bytes()
    dock.close(); store.close()
