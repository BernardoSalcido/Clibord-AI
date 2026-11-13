"""Qt bridge: SQLite and networking have one owner, away from the UI thread."""
import asyncio
import contextlib
import ctypes
import hashlib
import os
import sys
from pathlib import Path
import shutil
import threading
import traceback
import time
import uuid

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QMimeData, QObject, QTimer, Signal, Slot
from PySide6.QtGui import QClipboard, QImage, QImageReader

from .cli import pairing_payload
from .files import FileDock
from .protocol import ProtocolError
from .security import tls_identity
from .server import DockServer
from .store import Store
from .ai import AIConfig, AIError, LocalAI


class QtClipboard(QObject):
    """QClipboard is accessed only on Qt's thread; the worker reads a cache."""
    event_driven = True
    write_requested = Signal(object)
    external_changed = Signal(object)
    capture_error = Signal(str)

    def __init__(self, clipboard, sequence=None):
        super().__init__()
        self.clipboard = clipboard
        self._lock = threading.Lock()
        self._text = clipboard.text()
        self._revision = 0
        self._last = 0
        self._own_write = False
        self._origin = uuid.uuid4().hex.encode("ascii")
        self._last_written_text = None
        self._last_written_until = 0
        self._observed_text = None
        self._observed_files = None
        self._last_external_time = 0
        self._last_external_owner = None
        self._external_revision = None
        self._last_image_signature = None
        self._expect_copy = False
        self._read_retries = 0
        self.capture_image = self.capture_text = True
        self.capture_timer = QTimer(self)
        self.capture_timer.setSingleShot(True)
        self.capture_timer.timeout.connect(self._capture)
        clipboard.dataChanged.connect(self._changed)
        self.write_requested.connect(self._write)
        # Qt notifications are not always delivered for delayed rendering / Fn screenshot keys.
        # Poll only the OS change counter, not the user's image pixels on every tick.
        if sequence is None and os.name == "nt" and isinstance(clipboard, QClipboard):
            sequence = ctypes.windll.user32.GetClipboardSequenceNumber
            sequence.restype = ctypes.c_uint32
        if sequence is None and sys.platform == "darwin" and isinstance(clipboard, QClipboard):
            # Qt only notices another macOS application's clipboard change when
            # this application becomes active. changeCount works in the background.
            from AppKit import NSPasteboard
            sequence = lambda: NSPasteboard.generalPasteboard().changeCount()
        self.owner = None
        if os.name == "nt" and isinstance(clipboard, QClipboard):
            self.owner = ctypes.windll.user32.GetClipboardOwner
            self.owner.restype = ctypes.c_void_p
        self.sequence = sequence
        self._sequence_seen = sequence() if sequence else None
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll)
        if sequence: self.poll_timer.start(200)

    def _poll(self):
        current = self.sequence()
        if current != self._sequence_seen:
            self._changed()
        elif self._read_retries:
            self._read_retries -= 1
            self._changed(retry=False)

    @staticmethod
    def _has_image(mime):
        return bool(mime and (mime.hasImage() or any(
            "png" in name.lower() or name.lower() in ("image/jpeg", "image/bmp", "image/tiff")
            for name in mime.formats())))

    def _image_png(self, mime):
        picture = self.clipboard.image()
        if picture.isNull():
            for name in mime.formats():
                if "png" in name.lower() or name.lower() in ("image/jpeg", "image/bmp", "image/tiff"):
                    raw = bytes(mime.data(name))
                    if len(raw) > 8 * 1024 * 1024:
                        raise ValueError("Imagen mayor de 8 MiB. Recorta la captura.")
                    picture = QImage.fromData(raw)
                    if not picture.isNull(): break
        if picture.isNull(): return None
        if picture.width() * picture.height() > 24_000_000:
            raise ValueError("Imagen mayor de 24 megapíxeles. Recorta la captura.")
        data = QByteArray(); buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not picture.save(buffer, "PNG"):
            raise ValueError("No se pudo leer la imagen del portapapeles.")
        image = bytes(data)
        if len(image) > 8 * 1024 * 1024:
            raise ValueError("Imagen mayor de 8 MiB. Recorta la captura.")
        return image

    @Slot()
    def _changed(self, retry=True):
        text = self.clipboard.text()
        mime = self.clipboard.mimeData() if hasattr(self.clipboard, "mimeData") else None
        sequence = self.sequence() if self.sequence else None
        new_copy = sequence is not None and sequence != self._sequence_seen
        if new_copy:
            self._sequence_seen = sequence
        plain = not mime or (not self._has_image(mime) and not mime.hasUrls())
        paths = tuple(url.toLocalFile() for url in mime.urls() if url.isLocalFile()) if mime and not self._has_image(mime) else ()
        if paths and paths == self._observed_files and not new_copy:
            return
        self._observed_files = paths
        normalized = text.replace("\r\n", "\n") if plain else None
        tagged = bool(mime and bytes(mime.data("application/x-clipboard-ai-origin")) == self._origin)
        same_recent_write = (plain and normalized == self._last_written_text and
                             time.monotonic() < self._last_written_until)
        own = self._own_write or tagged or (same_recent_write and not self._expect_copy)
        if new_copy:
            self._expect_copy = False
        # A clipboard manager can republish a copied text with extra formats just
        # after it was read. That is not a second Ctrl+C. A repeat copy from the
        # same external owner remains a new input, even with identical text.
        format_echo = (new_copy and plain and normalized == self._observed_text and
                       time.monotonic() - self._last_external_time < 1 and
                       (not self.owner or self.owner() != self._last_external_owner))
        if retry and not own: self._read_retries = 5
        if tagged and self._has_image(mime):
            # Delayed image-format notifications from our own write are not new copies.
            self._external_revision = None
            self.capture_timer.stop()
            with self._lock: self._last = self._revision
            return
        # Windows/clipboard managers can notify several times, after setMimeData has returned.
        # Treat equal text as the same revision, including CRLF/HTML-format-only notifications.
        if plain and normalized == self._observed_text and not (new_copy and not own and not format_echo):
            if own:
                self._external_revision = None
                self.capture_timer.stop()
                with self._lock: self._last = self._revision
            return
        with self._lock:
            self._text = text
            self._revision += 1
            if own: self._last = self._revision
        self._observed_text = normalized
        if own:
            self._external_revision = None
            self.capture_timer.stop()
        else:
            self._last_written_text = None
            self._last_external_time = time.monotonic()
            self._last_external_owner = self.owner() if self.owner else None
            if not self._has_image(mime): self._last_image_signature = None
            if self.capture_image or self.capture_text:
                self._external_revision = self._revision
                self.capture_timer.start(100)

    def _capture(self):
        if self._external_revision != self._revision:
            return
        try:
            image = None
            mime = self.clipboard.mimeData() if hasattr(self.clipboard, "mimeData") else None
            if self._has_image(mime):
                if not self.capture_image: return
                image = self._image_png(mime)
                if image is None: return
                signature = hashlib.sha256(image).digest()
                if signature == self._last_image_signature: return
                self._last_image_signature = signature
            elif mime and mime.hasUrls() and any(url.isLocalFile() for url in mime.urls()):
                self.external_changed.emit(dict(revision=self._revision, text="", image=None,
                    files=[url.toLocalFile() for url in mime.urls() if url.isLocalFile()]))
                return
            else:
                # Some applications populate text after the change notification.
                if self.clipboard.text() != self._text:
                    self._changed(retry=False)
                    return
            if image or (self._text and self.capture_text):
                self.external_changed.emit(dict(revision=self._revision, text=self._text, image=image))
        except (ValueError, RuntimeError) as exc:
            self.capture_error.emit(str(exc))

    def read(self):
        with self._lock:
            return self._text

    def rearm(self):
        """A mode change must allow the next intentional copy of the same text."""
        self._observed_text = None

    def prepare_explicit_copy(self):
        """A repeated user copy must produce a fresh event, even with identical pixels."""
        self._observed_text = None
        self._last_image_signature = None
        self._expect_copy = True

    def cancel_explicit_copy(self):
        self._expect_copy = False

    def write_ui(self, text):
        request = {"text": text, "done": threading.Event(), "error": None}
        self._write(request)
        if request["error"]: raise RuntimeError(request["error"])

    def revision(self):
        with self._lock:
            return self._revision

    def changed(self):
        with self._lock:
            if self._revision == self._last:
                return None
            self._last = self._revision
            return self._text or None

    def write(self, text, expected_revision=None, cancel_event=None, expected_image=None):
        request = {"text": text, "expected_revision": expected_revision,
                   "written": False, "done": threading.Event(), "error": None, "cancelled": False,
                   "cancel_event": cancel_event, "expected_image": expected_image}
        self.write_requested.emit(request)
        if not request["done"].wait(3):
            with self._lock:
                request["cancelled"] = True
            raise RuntimeError("El portapapeles no respondió; el texto sigue guardado en el dock")
        if request["error"]:
            raise RuntimeError(request["error"])
        return request["written"]

    def write_image(self, path):
        request = {"image_path": str(path), "written": False, "done": threading.Event(),
                   "error": None, "cancelled": False}
        self.write_requested.emit(request)
        if not request["done"].wait(5):
            with self._lock:
                request["cancelled"] = True
            raise RuntimeError("El portapapeles no respondió; la imagen sigue guardada en el dock")
        if request["error"]:
            raise RuntimeError(request["error"])
        return request["written"]

    @Slot(object)
    def _write(self, request):
        try:
            if request.get("cancelled"):
                return
            if request.get("cancel_event") is not None and request["cancel_event"].is_set():
                return
            if self.sequence and self.sequence() != self._sequence_seen:
                self._poll()
            if request.get("expected_revision") is not None and self._revision != request["expected_revision"]:
                # New format notifications may advance the counter without changing the screenshot.
                expected = request.get("expected_image")
                mime = self.clipboard.mimeData() if hasattr(self.clipboard, "mimeData") else None
                if not expected or not self._has_image(mime) or self._image_png(mime) != expected:
                    return
            image_path = request.get("image_path")
            if not image_path and "\0" in request["text"]:
                raise ValueError("El portapapeles de texto no admite caracteres NUL")
            picture = None
            if image_path:
                source = Path(image_path)
                if source.stat().st_size > 32 * 1024 * 1024:
                    raise ValueError("Imagen mayor de 32 MiB; sigue disponible en el dock")
                reader = QImageReader(str(source))
                size = reader.size()
                if size.isValid() and size.width() * size.height() > 24_000_000:
                    raise ValueError("Imagen mayor de 24 megapíxeles; sigue disponible en el dock")
                picture = reader.read()
                if picture.isNull() or picture.width() * picture.height() > 24_000_000:
                    raise ValueError("No se pudo copiar la imagen; sigue disponible en el dock")
                if not hasattr(self.clipboard, "setMimeData"):
                    raise RuntimeError("Este portapapeles no admite imágenes")
            self._own_write = True
            self.capture_timer.stop()
            self._external_revision = None
            self._last_image_signature = None
            self._read_retries = 0
            self._last_written_text = None if image_path else request["text"].replace("\r\n", "\n")
            self._last_written_until = 0 if image_path else time.monotonic() + 1
            before = self._revision
            if hasattr(self.clipboard, "setMimeData"):
                mime = QMimeData()
                if image_path:
                    mime.setImageData(picture)
                else:
                    mime.setText(request["text"])
                mime.setData("application/x-clipboard-ai-origin", QByteArray(self._origin))
                self.clipboard.setMimeData(mime)
            else:
                self.clipboard.setText(request["text"])
            if image_path:
                if self.clipboard.image().isNull():
                    raise RuntimeError("Windows no actualizó la imagen del portapapeles; sigue guardada en el dock")
            elif self.clipboard.text() != request["text"]:
                raise RuntimeError("Windows no actualizó el portapapeles; el resultado sigue guardado en el dock")
            with self._lock:
                if self._revision == before: self._revision += 1
                self._text = "" if image_path else request["text"]
                self._last = self._revision
            self._observed_text = None if image_path else self._last_written_text
            request["written"] = True
        except Exception as exc:
            self._last_written_text = None
            self._last_written_until = 0
            request["error"] = str(exc)
        finally:
            self._own_write = False
            request["done"].set()


def export_copy(source, destination):
    source, destination = Path(source), Path(destination).expanduser().resolve()
    if source.resolve() == destination:
        raise ValueError("Elige una ubicación distinta de la copia administrada por el dock")
    temporary = destination.with_name("." + uuid.uuid4().hex + ".clipboard-ai.tmp")
    try:
        shutil.copyfile(source, temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return str(destination)


class Backend(QObject):
    snapshot = Signal(object)
    completed = Signal(str, object)
    error = Signal(str)
    notice = Signal(str)
    stopped = Signal()
    ai_state = Signal(str)
    ai_activity = Signal(str)

    def __init__(self, args, clipboard, auto_send=False, auto_receive=False, ai_config=None, warm_image=None):
        super().__init__()
        self.args, self.clipboard = args, clipboard
        self.auto_send, self.auto_receive = auto_send, auto_receive
        self.thread = None
        self.loop = None
        self.accepting = False
        self._stop_requested = threading.Event()
        self._last_snapshot = None
        self._text_changes = self._file_changes = -1
        self.ai_config = ai_config
        self.warm_image = warm_image
        self.ai = None
        self.ai_task = None
        self.ai_pending = None
        self.ai_generation = 0
        self.ai_event = None
        self.ai_last_input = None
        self.ai_busy = False
        self.ai_probes = set()
        self.remote_ai_task = None
        self.remote_ai_busy = False
        self.remote_clipboard_revisions = {}
        self.latest_remote_image = None

    def start(self):
        self.thread = threading.Thread(target=self._thread_main, name="ClipboardAI-network", daemon=False)
        self.thread.start()

    def _thread_main(self):
        try:
            with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop if os.name == "nt" else None) as runner:
                runner.run(self._run())
        except Exception as exc:
            try:
                self.args.data_dir.mkdir(parents=True, exist_ok=True)
                (self.args.data_dir / "startup-error.log").write_text(
                    traceback.format_exc(), encoding="utf-8")
            except OSError:
                pass
            self.error.emit(f"No se pudo iniciar el dock: {exc}. Consulta startup-error.log en la carpeta de datos de Clipboard AI.")
        finally:
            self.accepting = False
            self.ai_activity.emit("idle")
            self.stopped.emit()

    async def _run(self):
        self.loop = asyncio.get_running_loop()
        self.stop_event = asyncio.Event()
        self.commands = set()
        self.command_lock = asyncio.Lock()
        self.ai_lock = asyncio.Lock()
        self.remote_ai_event = asyncio.Event()
        self.store = self.files = self.listener = None
        tasks = []
        try:
            self.args.data_dir.mkdir(parents=True, exist_ok=True)
            self.args.data_dir.chmod(0o700)
            self.store = Store(self.args.data_dir / "dock.sqlite3")
            self.files = FileDock(self.args.data_dir / "Dock", self.store.device)
            self.context, self.fingerprint = tls_identity(self.args.data_dir)
            self.server = DockServer(self.store, self.clipboard, self.notice.emit, self.files)
            self.server.on_file_received = self._queue_remote_image
            self.server.on_text_received = self._queue_remote_text
            self.server.settings_getter = self._settings_snapshot
            self.server.settings_updater = self._apply_remote_settings
            self.server.auto_send, self.server.auto_receive = self.auto_send, self.auto_receive
            self.server.ai_text_active = bool(self.ai_config and self.ai_config.text_mode != "none")
            self.clipboard._last = self.clipboard.revision()
            self.paused = False
            self.listener = await self.server.listen(self.args.bind, self.args.port, self.context)
            self.port = self.listener.sockets[0].getsockname()[1]
            tasks = [asyncio.create_task(self.server.watch()), asyncio.create_task(self.server.watch_files(self.stop_event)),
                     asyncio.create_task(self._refresh())]
            for task in tasks:
                task.add_done_callback(self._watcher_done)
            self.accepting = True
            (self.args.data_dir / "startup-error.log").unlink(missing_ok=True)
            if self.ai_config is not None:
                self.ai = LocalAI(self.ai_config, self.ai_state.emit)
                self.ai_event = asyncio.Event()
                self.ai_task = asyncio.create_task(self._ai_worker())
                self.remote_ai_task = asyncio.create_task(self._remote_ai_worker())
            if self._stop_requested.is_set():
                self.stop_event.set()
            await self.stop_event.wait()
        finally:
            self.accepting = False
            if self.remote_ai_task:
                self.remote_ai_task.cancel()
                await asyncio.gather(self.remote_ai_task, return_exceptions=True)
            if self.ai_task:
                self.ai_task.cancel()
                await asyncio.gather(self.ai_task, return_exceptions=True)
            if self.ai:
                await self.ai.close()
            for task in self.ai_probes: task.cancel()
            await asyncio.gather(*self.ai_probes, return_exceptions=True)
            # Stop producers before waiting for accepted operations to commit their copies.
            for index, task in enumerate(tasks):
                if index != 1:
                    task.cancel()
            if len(tasks) > 1:
                self.stop_event.set()
                await asyncio.gather(tasks[1], return_exceptions=True)
            if self.commands:
                await asyncio.gather(*list(self.commands), return_exceptions=True)
            if self.listener:
                self.listener.close()
                await self.listener.wait_closed()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self.files:
                self.files.close()
            if self.store:
                self.store.close()

    def _watcher_done(self, task):
        if not task.cancelled() and task.exception():
            self.error.emit(f"Una tarea del dock se detuvo: {task.exception()}. Cierra y vuelve a abrir la aplicación.")

    async def _refresh(self):
        while True:
            self.emit_snapshot()
            await asyncio.sleep(0.7)

    def emit_snapshot(self):
        # Avoid rereading potentially large text histories on every progress tick.
        if self._text_changes != self.store.db.total_changes:
            self._text_changes = self.store.db.total_changes
            self._texts = self.store.history(1000)
            self._peers = self.store.peers()
            self._pending_text = self.store.pending_count()
        if self._file_changes != self.files.db.total_changes:
            self._file_changes = self.files.db.total_changes
            self._files = self.files.history()
            self._used = self.files.used()
            self._delivered = self.files.delivered_usage()
            self._pending_files = self.files.db.execute("SELECT COUNT(*) FROM files WHERE state IN ('pending','sending','receiving')").fetchone()[0]
        state = dict(texts=self._texts, files=self._files, peers=self._peers,
                     device=self.store.device, connected=bool(self.server.sessions),
                     shared_settings=self._settings_snapshot(),
                     connected_peers=list(self.server.sessions), paused=self.paused,
                     auto_send=self.server.auto_send, auto_receive=self.server.auto_receive,
                     pending_text=self._pending_text, used=self._used,
                     pending_files=self._pending_files,
                     delivered=self._delivered, inbox=str(self.files.inbox),
                     received=str(self.files.received), port=self.port)
        if state != self._last_snapshot:
            self._last_snapshot = state
            self.snapshot.emit(state)

    def request(self, action, *args):
        if not self.accepting or not self.loop:
            self.error.emit("El dock todavía no está disponible o se está cerrando.")
            return
        def schedule():
            if not self.accepting:
                return
            if action.startswith("ai_"):
                self._ai_request(action, args)
                return
            task = asyncio.create_task(self._command(action, args))
            self.commands.add(task)
            task.add_done_callback(self.commands.discard)
        self.loop.call_soon_threadsafe(schedule)

    def _ai_request(self, action, args):
        if not self.ai:
            return
        if action == "ai_probe":
            task = asyncio.create_task(self._ai_probe(args[0]))
            self.ai_probes.add(task); task.add_done_callback(self.ai_probes.discard)
        elif action == "ai_submit":
            source = args[0]
            mode = "image" if source.get("image") and self.ai_config.image else self.ai_config.text_mode if not source.get("image") else "none"
            if mode == "none": return
            identity = (mode, source["revision"])
            if identity == self.ai_last_input: return
            self.ai_last_input = identity
            self.ai_pending = ("process", mode, source, self.ai_generation)
            self.ai_event.set()
            self.ai_activity.emit("working")
            self.ai_state.emit("Procesando · hay una entrada más reciente" if self.ai_busy else "Entrada pendiente…")
        elif action in ("ai_cancel", "ai_config", "ai_prepare", "ai_release"):
            self.ai_generation += 1
            self.ai_pending = None
            self.ai_last_input = None
            self.ai_activity.emit("working" if self.remote_ai_busy or self._pending_remote_images() else "idle")
            if self.ai_task:
                self.ai_task.cancel()
            # The replacement worker awaits the previous cancellation before using the client.
            previous = self.ai_task
            if action == "ai_config":
                old_shared = (self.ai_config.image, self.ai_config.text_mode, self.ai_config.prompts)
                self.ai_config = args[0]
                self.server.ai_text_active = self.ai_config.text_mode != "none"
                self.remote_ai_event.set()
                if old_shared != (self.ai_config.image, self.ai_config.text_mode, self.ai_config.prompts):
                    self.store.advance_settings()
                    asyncio.create_task(self.server.broadcast_settings())
            self.ai_task = asyncio.create_task(self._ai_restart(previous, action))

    def _settings_snapshot(self):
        return dict(revision=self.store.settings_revision(),
                    values=dict(image=self.ai_config.image if self.ai_config else False,
                                text_mode=self.ai_config.text_mode if self.ai_config else "none",
                                prompts=self.ai_config.prompts if self.ai_config else {}))

    async def _apply_remote_settings(self, msg, peer):
        from dataclasses import replace
        if self.ai_config is None:
            raise ProtocolError("Este cerebro no tiene IA configurada")
        if type(msg.get("base_revision")) is not int or msg["base_revision"] != self.store.settings_revision():
            raise ProtocolError("Configuración modificada en otro dispositivo")
        patch = msg.get("changes")
        if (not isinstance(patch, dict) or not patch or not set(patch) <= {"image", "text_mode", "prompts"}
                or ("image" in patch and type(patch["image"]) is not bool)
                or ("text_mode" in patch and patch["text_mode"] not in ("none", "spelling", "grammar"))
                or ("prompts" in patch and (not isinstance(patch["prompts"], dict)
                    or set(patch["prompts"]) != {"image", "spelling", "grammar"}
                    or any(not isinstance(value, str) or not 0 < len(value) <= 8192
                           for value in patch["prompts"].values())))):
            raise ProtocolError("Cambio de configuración inválido")
        config = replace(self.ai_config, **patch).validate()
        config.save(self.args.data_dir)
        self._ai_request("ai_config", (config,))
        await self.server.broadcast_settings()

    async def _ai_probe(self, endpoint):
        client = None
        try:
            from dataclasses import replace
            config = replace(self.ai_config, endpoint=endpoint).validate()
            client = LocalAI(config)
            self.completed.emit("ai_probe", dict(models=await client.models()))
        except (ValueError, OSError) as exc:
            self.completed.emit("ai_probe", dict(error=str(exc)))
        finally:
            if client: await client.close()

    async def _ai_restart(self, previous, action):
        if previous:
            await asyncio.gather(previous, return_exceptions=True)
        self.ai_event.clear()
        if action == "ai_config":
            async with self.ai_lock:
                if (self.ai.config.endpoint, self.ai.config.model, self.ai.config.context) != (self.ai_config.endpoint, self.ai_config.model, self.ai_config.context):
                    await self.ai.close()
                    self.ai = LocalAI(self.ai_config, self.ai_state.emit)
                else:
                    self.ai.config = self.ai_config
        if action == "ai_release":
            try: await self.ai.release()
            except (AIError, ValueError) as exc: self.ai_state.emit(str(exc))
        elif action == "ai_cancel":
            self.ai_state.emit("Tarea cancelada")
        await self._ai_worker(preload=action in ("ai_config", "ai_prepare"))

    async def _ai_worker(self, preload=None):
        self.ai_busy = False
        if preload is None: preload = self.ai_config.preload
        if preload:
            try:
                self.ai_busy = True
                async with self.ai_lock:
                    await self.ai.prepare(self.warm_image)
            except (AIError, ValueError, KeyError) as exc:
                self.ai_state.emit(str(exc))
            finally:
                self.ai_busy = False
        while True:
            if self.ai_pending: self.ai_event.set()
            await self.ai_event.wait()
            self.ai_event.clear()
            if not self.ai_pending: continue
            _, mode, source, generation = self.ai_pending
            self.ai_pending = None
            self.ai_busy = True
            cancel_write = threading.Event()
            try:
                async with self.ai_lock:
                    result, stats = await self.ai.process(mode, source.get("text", ""), source.get("image"))
                if generation != self.ai_generation: continue
                item = self.store.ai_result(result, mode, source, stats)
                if source.get("image"):
                    written = await asyncio.to_thread(self.clipboard.write, result, source["revision"], cancel_write, source["image"])
                else:
                    written = await asyncio.to_thread(self.clipboard.write, result, source["revision"], cancel_write)
                if not self.ai_pending and not self.remote_ai_busy and not self._pending_remote_images():
                    self.ai_activity.emit("copied" if written else "saved")
                if written and self.server.auto_send:
                    try:
                        await self.server.publish_existing(item["id"])
                    except (ValueError, OSError) as exc:
                        self.notice.emit("Resultado guardado y copiado; no pudo enviarse: " + str(exc))
                self.completed.emit("ai_result", dict(id=item["id"], written=written, stats=stats))
                self.ai_state.emit("IA lista")
                self.emit_snapshot()
            except (AIError, ValueError, RuntimeError, OSError, KeyError) as exc:
                self.ai_last_input = None
                if not self.ai_pending and not self.remote_ai_busy and not self._pending_remote_images():
                    self.ai_activity.emit("error")
                self.ai_state.emit("Error de IA: " + str(exc))
            finally:
                cancel_write.set()
                self.ai_busy = False

    def _queue_remote_image(self, source_id, peer):
        row = self.files.get(source_id)
        import json
        meta = json.loads(row["meta"])
        if (row["direction"] == "in" and row["state"] == "delivered"
                and meta["origin"] == peer and meta["mime"].startswith("image/")):
            if self.server.auto_receive and hasattr(self.clipboard, "write_image"):
                try:
                    self.clipboard.write_image(row["path"])
                except (OSError, ValueError, RuntimeError) as exc:
                    self.notice.emit(f"Imagen guardada en dock; no se pudo copiar: {exc}")
            if self.ai and self.ai_config.image and self.store.queue_remote_image(source_id, peer):
                self.remote_clipboard_revisions[source_id] = self.clipboard.revision()
                self.latest_remote_image = source_id
                self.remote_ai_event.set()
                self.ai_activity.emit("working")
                asyncio.create_task(self.server.send_ai_status(peer, source_id, "image", "pending"))

    def _queue_remote_text(self, item, peer):
        if self.ai and self.ai_config.text_mode != "none":
            if self.store.queue_remote_text(item["id"], peer, item["text"], self.ai_config.text_mode):
                self.remote_ai_event.set()
                asyncio.create_task(self.server.send_ai_status(peer, item["id"], self.ai_config.text_mode, "pending"))

    def _pending_remote_images(self):
        return bool(self.store and any(job["mode"] == "image" for job in self.store.remote_image_jobs()))

    async def _remote_ai_worker(self):
        while True:
            pending = self.store.remote_image_jobs()
            if not pending:
                self.remote_ai_event.clear()
                await self.remote_ai_event.wait()
                continue
            job = pending[0]
            source_id = job["source_id"]
            image_job = job["mode"] == "image"
            if image_job:
                self.remote_ai_busy = True
                self.ai_activity.emit("working")
            outcome = "error"
            self.store.remote_image_state(source_id, "running")
            await self.server.send_ai_status(job["source_origin"], source_id, job["mode"], "running")
            try:
                if job["result_id"]:
                    item_id = job["result_id"]
                else:
                    image = None
                    if job["mode"] == "image":
                        row = self.files.get(source_id)
                        image = await asyncio.to_thread(Path(row["path"]).read_bytes)
                    async with self.ai_lock:
                        result, stats = await self.ai.process(job["mode"], job["source_text"], image)
                    item = self.store.ai_result(result, job["mode"],
                                                {"text": job["source_text"], "image": image}, stats)
                    item_id = item["id"]
                    self.store.remote_image_state(source_id, "running", item_id)
                if image_job:
                    expected_revision = self.remote_clipboard_revisions.get(source_id)
                    written = False
                    if expected_revision is not None and self.latest_remote_image == source_id:
                        try:
                            text = self.store.get(item_id)["text"]
                            written = bool(await asyncio.to_thread(self.clipboard.write, text, expected_revision))
                        except (OSError, ValueError, RuntimeError) as exc:
                            self.notice.emit("Markdown guardado en Textos; no se pudo copiar: " + str(exc))
                    outcome = "copied" if written else "saved"
                await self.server.publish_existing(item_id)
                self.store.remote_image_state(source_id, "done", item_id)
                await self.server.send_ai_status(job["source_origin"], source_id, job["mode"], "done")
                self.notice.emit("Resultado de IA del teléfono distribuido.")
                self.emit_snapshot()
            except asyncio.CancelledError:
                self.store.remote_image_state(source_id, "pending")
                raise
            except (AIError, ValueError, RuntimeError, OSError, KeyError, ProtocolError) as exc:
                self.store.remote_image_state(source_id, "error", error=str(exc))
                await self.server.send_ai_status(job["source_origin"], source_id, job["mode"], "error")
                self.notice.emit("No se pudo convertir la imagen recibida: " + str(exc))
            finally:
                if image_job:
                    self.remote_ai_busy = False
                    self.remote_clipboard_revisions.pop(source_id, None)
                    self.ai_activity.emit("working" if self.ai_busy or self.ai_pending or self._pending_remote_images()
                                          else outcome)

    async def _command(self, action, args):
        async with self.command_lock:
            try:
                value = await self._execute(action, *args)
                self.completed.emit(action, value)
                self.emit_snapshot()
            except Exception as exc:
                self.error.emit(f"No se pudo completar la acción: {exc}")

    async def _execute(self, action, *args):
        if action == "send":
            return await self.server.publish(args[0])
        if action == "clipboard_text":
            return await self.server.publish(args[0])
        if action == "capture_image":
            item = self.files.save_capture(args[0])
            for ws in list(self.server.file_peers):
                with contextlib.suppress(Exception):
                    await self.server.offer_files(ws)
            return item
        if action == "capture_image_local":
            return self.files.save_capture(args[0], share=False)
        if action == "ai_original":
            record = self.store.db.execute("SELECT source_text,source_image FROM ai_records WHERE result_id=?", (args[0],)).fetchone()
            if not record:
                raise ValueError("La entrada original ya no está conservada en el historial de IA.")
            return dict(text=record[0], image=record[1])
        if action == "clip":
            return await self.server.publish(self.clipboard.read())
        if action == "files":
            errors = []
            added = 0
            for path in args[0]:
                try:
                    await self.server.add_file(Path(path))
                    added += 1
                except (OSError, ValueError) as exc:
                    errors.append(f"{Path(path).name}: {exc}")
            return dict(added=added, errors=errors)
        if action == "copy":
            self.clipboard.write(self.store.get(args[0])["text"])
        elif action == "delete_text":
            self.store.delete(args[0])
        elif action == "clear_texts":
            if self.ai:
                self._ai_request("ai_cancel", ())
            return self.store.clear_texts()
        elif action in ("cancel_file", "delete_file"):
            (self.files.cancel if action == "cancel_file" else self.files.delete)(args[0])
            for ws in list(self.server.file_peers):
                with contextlib.suppress(Exception):
                    await self.server.offer_files(ws)
        elif action == "clear":
            return self.files.clear_delivered()
        elif action == "file_path":
            row = self.files.get(args[0])
            capture = row["direction"] == "out" and Path(row["path"]).parent == self.files.captures
            if row["state"] != "delivered" and not (capture and row["state"] in ("pending", "sending")):
                raise ProtocolError("Espera a que el archivo esté entregado")
            if not Path(row["path"]).is_file():
                raise FileNotFoundError("La copia ya no está en el dock")
            mode, destination = args[1:]
            if mode == "save":
                path = await asyncio.to_thread(export_copy, row["path"], destination)
                return dict(mode=mode, path=path)
            path = Path(row["path"])
            if row["direction"] == "out" and not capture and mode == "open":
                raise ValueError("Guarda una copia para abrirla con su nombre original")
            return dict(mode=mode, path=str(path))
        elif action == "pair":
            address = args[0].strip()
            if not address or address == "127.0.0.1":
                raise ValueError("Elige la dirección de la red compartida con el teléfono")
            if self.paused:
                raise ValueError("Reanuda la conexión antes de vincular")
            return pairing_payload(self.server, self.fingerprint, address, self.port)
        elif action == "close_pair":
            self.server.pairing.code = None
        elif action == "revoke":
            return await self.server.revoke(args[0])
        elif action == "automatic":
            self.clipboard._last = self.clipboard.revision()
            self.server.auto_send, self.server.auto_receive = args
            return args
        elif action == "pause":
            if not self.paused:
                self.listener.close()
                await self.listener.wait_closed()
                self.listener = None
                self.server.pairing.code = None
                self.paused = True
            else:
                self.listener = await self.server.listen(self.args.bind, self.port, self.context)
                self.paused = False
            return self.paused
        else:
            raise ValueError("Acción desconocida")

    def stop(self):
        self._stop_requested.set()
        self.accepting = False
        if self.loop and not self.loop.is_closed() and hasattr(self, "stop_event"):
            self.loop.call_soon_threadsafe(self.stop_event.set)
