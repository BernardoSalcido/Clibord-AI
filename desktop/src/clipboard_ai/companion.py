"""Desktop companion for a paired Clipboard AI brain.

The wire contract is shared with Android. This worker owns SQLite, files and
the WebSocket; Qt only receives immutable snapshots and issues commands.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import re
import socket
import ssl
import threading
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, Signal
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from .files import CAPABILITY, FileDock
from .gui_backend import export_copy
from .protocol import MAX_MESSAGE, ProtocolError, decode, encode, identifier
from .store import Store


def pairing_data(raw):
    """Validate pasted pairing data before any network operation."""
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Pega el bloque JSON completo de vinculación") from exc
    if not isinstance(value, dict) or value.get("v") != 1:
        raise ValueError("Versión de vinculación desconocida")
    host, port, fingerprint, code = (value.get(key) for key in ("host", "port", "fingerprint", "code"))
    if not isinstance(host, str) or not host or len(host) > 253 or any(ch in host for ch in "/\\@?# "):
        raise ValueError("Dirección de red inválida")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Puerto inválido")
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", fingerprint):
        raise ValueError("Huella TLS inválida")
    if not isinstance(code, str) or not 8 <= len(code) <= 128:
        raise ValueError("Código de vinculación inválido")
    return dict(host=host, port=port, fingerprint=fingerprint.lower(), code=code)


def pinned_url(host, port):
    address = f"[{host}]" if ":" in host else host
    url = f"wss://{address}:{port}/"
    if urlsplit(url).hostname is None:
        raise ValueError("Dirección de red inválida")
    return url


def _ssl_context():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # Exact certificate pin is checked below, before authentication.
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def verify_pin(ws, expected):
    ssl_object = ws.transport.get_extra_info("ssl_object")
    actual = hashlib.sha256(ssl_object.getpeercert(binary_form=True)).hexdigest() if ssl_object else ""
    if actual != expected:
        raise ProtocolError("La huella TLS del cerebro cambió. Conexión rechazada.")


class CompanionBackend(QObject):
    snapshot = Signal(object)
    completed = Signal(str, object)
    error = Signal(str)
    notice = Signal(str)
    stopped = Signal()
    ai_state = Signal(str)
    ai_activity = Signal(str)

    def __init__(self, args, clipboard, auto_receive=True):
        super().__init__()
        self.args, self.clipboard = args, clipboard
        self.auto_receive = auto_receive
        self.accepting = False
        self.thread = self.loop = None
        self._stop_requested = threading.Event()
        self.credentials_path = args.data_dir / "companion.json"
        self.pending_path = args.data_dir / "pending-settings.json"
        self.credentials = None
        self.pending_settings = None
        self.settings = dict(revision=0, values={})
        self.paused = False
        self.connected = False
        self.ws = None
        self.server_id = None
        self.devices = []
        self.source_revisions = {}
        self._last_snapshot = None

    def start(self):
        self.thread = threading.Thread(target=self._thread_main, name="ClipboardAI-companion", daemon=False)
        self.thread.start()

    def _thread_main(self):
        try:
            with asyncio.Runner() as runner:
                runner.run(self._run())
        except Exception as exc:
            self.error.emit("No se pudo iniciar el dock del Mac: " + str(exc))
        finally:
            self.accepting = False
            self.stopped.emit()

    async def _run(self):
        self.loop = asyncio.get_running_loop()
        self.args.data_dir.mkdir(parents=True, exist_ok=True)
        self.args.data_dir.chmod(0o700)
        self.store = Store(self.args.data_dir / "dock.sqlite3")
        self.files = FileDock(self.args.data_dir / "Dock", self.store.device)
        self.credentials = self._load_json(self.credentials_path)
        self.pending_settings = self._load_json(self.pending_path)
        self.stop_event = asyncio.Event()
        self.wake = asyncio.Event()
        self.accepting = True
        if self._stop_requested.is_set(): self.stop_event.set()
        refresh = asyncio.create_task(self._refresh())
        network = asyncio.create_task(self._network())
        try:
            await self.stop_event.wait()
        finally:
            self.accepting = False
            refresh.cancel(); network.cancel()
            await asyncio.gather(refresh, network, return_exceptions=True)
            if self.ws:
                await self.ws.close()
            self.files.close(); self.store.close()

    @staticmethod
    def _load_json(path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            return None

    @staticmethod
    def _save_json(path, value):
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value), encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(path)

    def _remember_source(self, source_id):
        if hasattr(self.clipboard, "revision"):
            self.source_revisions[source_id] = self.clipboard.revision()
            while len(self.source_revisions) > 100:
                self.source_revisions.pop(next(iter(self.source_revisions)))

    async def _refresh(self):
        while True:
            self.emit_snapshot()
            await asyncio.sleep(0.7)

    def emit_snapshot(self):
        peers = [dict(id=self.credentials["server"], name="Cerebro")] if self.credentials else []
        state = dict(texts=self.store.history(1000), files=self.files.history(), peers=peers,
                     device=self.store.device, connected=self.connected,
                     connected_peers=[row["id"] for row in self.devices if row.get("connected")],
                     shared_settings=self.settings, devices=self.devices, paused=self.paused, auto_send=False,
                     auto_receive=self.auto_receive, pending_text=self.store.pending_count(),
                     pending_files=self.files.db.execute("SELECT COUNT(*) FROM files WHERE state IN ('pending','sending','receiving')").fetchone()[0],
                     used=self.files.used(), delivered=self.files.delivered_usage(),
                     inbox=str(self.files.inbox), received=str(self.files.received), port=0)
        if state != self._last_snapshot:
            self._last_snapshot = state
            self.snapshot.emit(state)

    def request(self, action, *args):
        if not self.accepting or not self.loop:
            self.error.emit("El dock todavía no está disponible")
            return
        async def run():
            try:
                value = await self._execute(action, *args)
                self.completed.emit(action, value)
                self.emit_snapshot()
            except Exception as exc:
                self.error.emit("No se pudo completar la acción: " + str(exc))
        self.loop.call_soon_threadsafe(lambda: asyncio.create_task(run()))

    async def _execute(self, action, *args):
        if action == "pair":
            data = pairing_data(args[0])
            if self.credentials:
                raise ValueError("Ya hay un cerebro vinculado. Desvincúlalo primero en Ajustes.")
            async with connect(pinned_url(data["host"], data["port"]), ssl=_ssl_context(), proxy=None,
                               compression=None, max_size=MAX_MESSAGE, open_timeout=10) as ws:
                verify_pin(ws, data["fingerprint"])
                await ws.send(encode("pair", device=self.store.device, name=socket.gethostname()[:80], code=data["code"]))
                reply = decode(await asyncio.wait_for(ws.recv(), 15))
                if reply["type"] != "paired":
                    raise ProtocolError(reply.get("message", "Vinculación rechazada"))
                server = identifier(reply.get("server"))
                token = reply.get("token")
                if not isinstance(token, str) or not 16 <= len(token) <= 128:
                    raise ProtocolError("Credencial de vinculación inválida")
                self.credentials = dict(host=data["host"], port=data["port"],
                                        fingerprint=data["fingerprint"], server=server, token=token)
                self._save_json(self.credentials_path, self.credentials)
                self.wake.set()
                return "Mac vinculado; conectando…"
        if action == "revoke":
            if self.credentials and args[0] == self.credentials["server"]:
                self.credentials_path.unlink(missing_ok=True)
                self.credentials = None
                if self.ws: await self.ws.close()
                self.wake.set()
                return True
            raise ValueError("Para desvincular otro dispositivo, usa el cerebro")
        if action in ("send", "clipboard_text", "clip"):
            text = self.clipboard.read() if action == "clip" else args[0]
            item = self.store.create(text)
            if self.settings.get("values", {}).get("text_mode") in ("spelling", "grammar"):
                self._remember_source(item["id"])
            if self.connected: await self.ws.send(encode("item", item=item))
            return item if action != "clip" else None
        if action in ("capture_image", "capture_image_local"):
            item = self.files.save_capture(args[0], share=True)
            if self.settings.get("values", {}).get("image"):
                self._remember_source(item["id"])
            await self._offer_files()
            return item
        if action == "files":
            errors = []; added = 0
            for path in args[0]:
                try:
                    self.files.add(Path(path)); added += 1
                except (OSError, ValueError) as exc:
                    errors.append(f"{Path(path).name}: {exc}")
            await self._offer_files()
            return dict(added=added, errors=errors)
        if action == "copy":
            self.clipboard.write(self.store.get(args[0])["text"])
            return None
        if action == "delete_text": return self.store.delete(args[0])
        if action == "clear_texts": return self.store.clear_texts()
        if action in ("cancel_file", "delete_file"):
            (self.files.cancel if action == "cancel_file" else self.files.delete)(args[0])
            await self._offer_files(); return None
        if action == "clear": return self.files.clear_delivered()
        if action == "file_path":
            row = self.files.get(args[0])
            if row["state"] != "delivered" or not Path(row["path"]).is_file():
                raise ValueError("Espera a que termine la transferencia")
            mode, destination = args[1:]
            if mode == "save": return dict(mode=mode, path=await asyncio.to_thread(export_copy, row["path"], destination))
            path = Path(row["path"])
            return dict(mode=mode, path=str(path.parent if mode == "folder" else path))
        if action == "automatic":
            self.auto_receive = bool(args[1]); return args
        if action == "pause":
            self.paused = not self.paused
            if self.paused and self.ws: await self.ws.close()
            self.wake.set(); return self.paused
        if action == "ai_config":
            config = args[0]
            changes = dict(image=config.image, text_mode=config.text_mode, prompts=config.prompts)
            self.pending_settings = dict(base_revision=self.settings["revision"], changes=changes)
            self._save_json(self.pending_path, self.pending_settings)
            await self._send_settings()
            return None
        if action == "ai_submit":
            source = args[0]
            if source.get("manual"):
                # A selection already in history has a stable ID on the brain;
                # resend a fresh item/file to request a new independent job.
                if source.get("image"):
                    item = self.files.save_capture(source["image"], share=True)
                    self._remember_source(item["id"])
                    await self._offer_files()
                elif source.get("text"):
                    item = self.store.create(source["text"])
                    self._remember_source(item["id"])
                    if self.connected: await self.ws.send(encode("item", item=item))
            # A new clipboard copy was already sent by clipboard_text or
            # capture_image and will be processed once by the brain.
            return None
        if action in ("ai_cancel", "close_pair"):
            return None
        raise ValueError("Acción no disponible en el Mac conectado")

    async def _network(self):
        delay = 1
        while True:
            if not self.credentials or self.paused:
                self.wake.clear(); await self.wake.wait(); continue
            credentials = self.credentials.copy()
            try:
                async with connect(pinned_url(credentials["host"], credentials["port"]), ssl=_ssl_context(), proxy=None,
                                   compression=None, max_size=MAX_MESSAGE, open_timeout=10,
                                   ping_interval=20, ping_timeout=20) as ws:
                    verify_pin(ws, credentials["fingerprint"])
                    self.ws = ws
                    await ws.send(encode("hello", device=self.store.device, token=credentials["token"],
                                         capabilities=[CAPABILITY, "hub-v2"]))
                    await self._session(ws, credentials)
                    delay = 1
            except asyncio.CancelledError:
                raise
            except (OSError, ValueError, ConnectionClosed, asyncio.TimeoutError) as exc:
                self.notice.emit("Cerebro sin conexión: " + str(exc)[:180])
            finally:
                self.connected = False; self.ws = None; self.server_id = None; self.devices = []
                self.ai_activity.emit("idle")
                self.emit_snapshot()
            self.wake.clear()
            try:
                await asyncio.wait_for(self.wake.wait(), delay)
            except asyncio.TimeoutError:
                delay = min(delay * 2, 30)

    async def _session(self, ws, credentials):
        ready = False
        async for raw in ws:
            msg = decode(raw)
            kind = msg["type"]
            if kind == "welcome":
                if identifier(msg.get("server")) != credentials["server"]:
                    raise ProtocolError("Identidad del cerebro incorrecta")
                self.server_id = credentials["server"]
            elif kind in ("settings", "settings_conflict"):
                self.settings = dict(revision=msg["revision"], values=msg["values"])
                pending = self.pending_settings
                if pending:
                    if all(msg["values"].get(k) == v for k, v in pending["changes"].items()):
                        self.pending_settings = None; self.pending_path.unlink(missing_ok=True)
                    elif kind == "settings_conflict" or pending["base_revision"] != msg["revision"]:
                        self.notice.emit("Ajustes cambiados en otro dispositivo; revisa tus cambios antes de reenviar")
                    elif ready:
                        await self._send_settings()
                self.emit_snapshot()
            elif kind == "devices":
                self.devices = msg.get("items", [])
                self.emit_snapshot()
            elif kind == "item":
                if not self.server_id: raise ProtocolError("Falta saludo del cerebro")
                item = msg.get("item", {})
                fresh = self.store.receive(item, identifier(item.get("origin")))
                await ws.send(encode("ack", id=item["id"]))
                if fresh and ready and msg.get("live") and self.auto_receive:
                    result = msg.get("result")
                    expected = self.source_revisions.pop(result.get("source_id"), None) if isinstance(result, dict) else None
                    try:
                        written = self.clipboard.write(item["text"], expected_revision=expected) if expected is not None else self.clipboard.write(item["text"])
                        if written is False:
                            self.notice.emit("Resultado guardado en Textos; el portapapeles del Mac cambió entretanto")
                        if result:
                            self.ai_activity.emit("copied" if written is not False else "saved")
                    except (OSError, ValueError, RuntimeError) as exc:
                        self.notice.emit("Texto guardado en el dock; no se pudo copiar: " + str(exc))
                        if result: self.ai_activity.emit("saved")
                self.emit_snapshot()
            elif kind == "ready":
                if not self.server_id: raise ProtocolError("Falta saludo del cerebro")
                self.connected = True; ready = True
                await self._send_settings()
                for item in self.store.pending():
                    await ws.send(encode("item", item=item))
                await ws.send(encode("ready"))
                await self._offer_files()
                self.emit_snapshot()
            elif kind == "ack":
                self.store.acknowledge(identifier(msg.get("id")))
                self.emit_snapshot()
            elif kind.startswith("file_"):
                reply = self.files.handle(msg, self.server_id, relayed=True)
                if reply: await ws.send(json.dumps(reply))
                if kind in ("file_done", "file_error", "file_cancelled") or reply and reply["type"] == "file_done":
                    await self._offer_files()
                if reply and reply["type"] == "file_done" and self.auto_receive:
                    row = self.files.get(reply["id"])
                    if row["direction"] == "in" and json.loads(row["meta"])["mime"].startswith("image/"):
                        try:
                            self.clipboard.write_image(row["path"])
                        except (OSError, ValueError, RuntimeError) as exc:
                            self.notice.emit("Imagen guardada en el dock; no se pudo copiar: " + str(exc))
                self.emit_snapshot()
            elif kind == "ai_status":
                state = msg.get("state")
                self.ai_state.emit({"pending": "En cola", "running": "Procesando", "done": "IA lista", "error": "Error de IA"}.get(state, "IA"))
                self.ai_activity.emit("working" if state in ("pending", "running") else "error" if state == "error" else "idle")
            elif kind == "error":
                raise ProtocolError(str(msg.get("message", "Error de conexión")))

    async def _offer_files(self):
        if self.connected and self.ws:
            for message in self.files.notices() + self.files.offers():
                await self.ws.send(json.dumps(message))

    async def _send_settings(self):
        if self.connected and self.ws and self.pending_settings:
            pending = self.pending_settings
            if pending["base_revision"] == self.settings["revision"]:
                await self.ws.send(encode("settings_update", **pending))

    def stop(self):
        self._stop_requested.set(); self.accepting = False
        if self.loop and not self.loop.is_closed() and hasattr(self, "stop_event"):
            self.loop.call_soon_threadsafe(self.stop_event.set)
