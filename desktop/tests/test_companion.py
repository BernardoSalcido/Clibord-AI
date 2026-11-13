import asyncio
import base64
import json
import os
from types import SimpleNamespace

import pytest

from clipboard_ai.companion import CompanionBackend, pairing_data
from clipboard_ai.files import FileDock
from clipboard_ai.protocol import ProtocolError
from clipboard_ai.security import tls_identity
from clipboard_ai.server import DockServer
from clipboard_ai.store import Store

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class Clipboard:
    def __init__(self):
        self.text = ""
        self.images = []
        self.rev = 0

    def read(self): return self.text
    def revision(self): return self.rev
    def write(self, text, expected_revision=None):
        if expected_revision is not None and expected_revision != self.rev:
            return False
        self.text = text; self.rev += 1
        return True
    def write_image(self, path): self.images.append(path); self.rev += 1


async def until(predicate):
    for _ in range(150):
        if predicate(): return
        await asyncio.sleep(0.05)
    raise AssertionError("La conexión no completó el intercambio")


def test_pairing_data_rejects_invalid_host_or_pin():
    good = dict(v=1, host="127.0.0.1", port=45821, fingerprint="a" * 64, code="secret-code")
    assert pairing_data(json.dumps(good))["fingerprint"] == "a" * 64
    for changed in (dict(host="host/path"), dict(port=0), dict(fingerprint="bad"), dict(code="x")):
        with pytest.raises(ValueError):
            pairing_data(json.dumps({**good, **changed}))


def test_mac_shortcut_accepts_case_and_caps_lock(monkeypatch):
    from clipboard_ai import macos_platform
    flags = SimpleNamespace(NSEventModifierFlagOption=1, NSEventModifierFlagCommand=2,
                            NSEventModifierFlagShift=4, NSEventModifierFlagControl=8)
    monkeypatch.setattr(macos_platform, "_native", lambda: (flags, None))
    activated = []
    hotkeys = macos_platform.MacHotkeys({"send": lambda: activated.append(True)})
    hotkeys.bindings[(9, ord("C"))] = "send"  # Physical Control+Option+C.
    class Event:
        def __init__(self, modifiers): self.modifiers = modifiers
        def charactersIgnoringModifiers(self): return "c"
        def modifierFlags(self): return self.modifiers
        def keyCode(self): return 8
        def isARepeat(self): return False
    assert hotkeys._dispatch(Event(9))
    assert hotkeys._dispatch(Event(13))  # Shift/Caps Lock does not change the action.
    assert len(activated) == 2


def test_companion_pairs_exchanges_text_and_image_over_existing_server(tmp_path):
    async def scenario():
        brain = tmp_path / "brain"; brain.mkdir()
        mac = tmp_path / "mac"; mac.mkdir()
        brain_store = Store(brain / "dock.sqlite3")
        brain_files = FileDock(brain / "Dock", brain_store.device)
        server = DockServer(brain_store, notify=lambda _: None, files=brain_files)
        shared = dict(revision=0, values=dict(image=False, text_mode="none",
                    prompts=dict(image="Imagen", spelling="Ortografía", grammar="Gramática")))
        server.settings_getter = lambda: shared.copy()
        async def update_settings(msg, peer):
            if msg["base_revision"] != shared["revision"]:
                raise ProtocolError("Revisión anterior")
            shared["values"].update(msg["changes"])
            shared["revision"] += 1
            await server.broadcast_settings()
        server.settings_updater = update_settings
        context, fingerprint = tls_identity(brain)
        clipboard = Clipboard()
        companion = CompanionBackend(SimpleNamespace(data_dir=mac), clipboard)
        companion.store = Store(mac / "dock.sqlite3")
        companion.files = FileDock(mac / "Dock", companion.store.device)
        companion.wake = asyncio.Event()
        companion.accepting = True
        async with server.listen("127.0.0.1", 0, context) as listener:
            port = listener.sockets[0].getsockname()[1]
            payload = json.dumps(dict(v=1, host="127.0.0.1", port=port,
                                      fingerprint=fingerprint, code=server.pairing.open()))
            await companion._execute("pair", payload)
            assert companion.credentials["server"] == brain_store.device
            network = asyncio.create_task(companion._network())
            try:
                await until(lambda: companion.connected)
                await companion._execute("send", "Mac → cerebro")
                await until(lambda: any(row["text"] == "Mac → cerebro" for row in brain_store.history()))
                await until(lambda: companion.store.pending_count() == 0)
                await server.publish("cerebro → Mac")
                await until(lambda: clipboard.text == "cerebro → Mac")
                png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==")
                await companion._execute("capture_image", png)
                await until(lambda: any(row["direction"] == "in" and row["state"] == "delivered"
                                        for row in brain_files.history()))
                source = brain / "respuesta.png"
                source.write_bytes(png)
                await server.add_file(source)
                await until(lambda: bool(clipboard.images))
                assert any(row["direction"] == "in" and row["state"] == "delivered"
                           for row in companion.files.history())
                config = SimpleNamespace(image=True, text_mode="grammar", prompts=shared["values"]["prompts"])
                await companion._execute("ai_config", config)
                await until(lambda: shared["values"]["image"] and companion.pending_settings is None)
                assert shared["revision"] == 1
                await companion._execute("ai_submit", dict(manual=True, text="historial para reprocesar", image=None))
                await until(lambda: any(row["text"] == "historial para reprocesar" for row in brain_store.history()))
                original = await companion._execute("send", "corrige esto")
                await until(lambda: any(row["id"] == original["id"] for row in brain_store.history()))
                clipboard.text = "copia más reciente"; clipboard.rev += 1
                brain_store.queue_remote_text(original["id"], companion.store.device, original["text"], "grammar")
                correction = brain_store.ai_result("Corrige esto", "grammar", dict(text=original["text"], image=None), {})
                brain_store.remote_image_state(original["id"], "done", correction["id"])
                await server.publish_existing(correction["id"])
                await until(lambda: any(row["id"] == correction["id"] for row in companion.store.history()))
                assert clipboard.text == "copia más reciente"
                network.cancel()
                await asyncio.gather(network, return_exceptions=True)
                await companion._execute("send", "pendiente tras desconexión")
                assert companion.store.pending_count() == 1
                network = asyncio.create_task(companion._network())
                await until(lambda: any(row["text"] == "pendiente tras desconexión"
                                        for row in brain_store.history()))
                await until(lambda: companion.store.pending_count() == 0)
                assert companion.credentials_path.is_file()
            finally:
                network.cancel()
                await asyncio.gather(network, return_exceptions=True)
        companion.files.close(); companion.store.close(); brain_files.close(); brain_store.close()
    asyncio.run(asyncio.wait_for(scenario(), 20))


def test_companion_dock_constructs_with_existing_ui(tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon
    from clipboard_ai.gui import MacCompanionWindow
    from clipboard_ai.desktop_platform import WindowsHotkeys
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    monkeypatch.setattr(WindowsHotkeys, "configure", lambda self, values: [])
    if os.sys.platform == "darwin":
        from clipboard_ai.macos_platform import MacHotkeys
        monkeypatch.setattr(MacHotkeys, "configure", lambda self, values: [])
    app = QApplication.instance() or QApplication([])
    args = SimpleNamespace(data_dir=tmp_path, bind="127.0.0.1", port=0, advertise=None, brain=False)
    window = MacCompanionWindow(args, QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat))
    try:
        assert window.pair_button.text() == "Vincular cerebro"
        assert "cerebro" in window.subtitle.text()
        window.backend.store = Store(tmp_path / "dock.sqlite3")
        window.backend.files = FileDock(tmp_path / "Dock", window.backend.store.device)
        window.backend.emit_snapshot()
        app.processEvents()
        assert "Esperando al cerebro" in window.connection.text()
    finally:
        window.backend.files.close(); window.backend.store.close()
        window.hotkeys.close(); window.tray.hide(); window.cursor_activity.close(); window.hide()
