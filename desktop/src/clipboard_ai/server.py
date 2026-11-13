import asyncio
import contextlib
import json

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from .protocol import MAX_MESSAGE, ProtocolError, decode, encode, identifier
from .security import Pairing
from .files import CAPABILITY


class DockServer:
    def __init__(self, store, clipboard=None, notify=print, files=None):
        self.store, self.clipboard, self.notify = store, clipboard, notify
        self.pairing = Pairing()
        self.sessions = {}
        self.auto_receive = False
        self.auto_send = False
        self.files = files
        self.file_peers = set()
        self.file_last = {}
        self.relay_peers = set()
        self.on_file_received = None
        self.on_text_received = None
        self.settings_getter = None
        self.settings_updater = None

    async def handler(self, ws):
        peer = None
        retry_task = None
        try:
            hello = decode(await asyncio.wait_for(ws.recv(), timeout=15))
            peer = identifier(hello.get("device"))
            if peer == self.store.device:
                raise ProtocolError("El identificador remoto coincide con el local")
            if hello["type"] == "pair":
                name = hello.get("name", "Android")
                if not isinstance(name, str) or not name or len(name) > 80:
                    raise ProtocolError("Nombre de dispositivo inválido")
                if not self.pairing.consume(hello.get("code")):
                    raise ProtocolError("Vinculación caducada, incorrecta o cerrada")
                token = self.store.pair(peer, name)
                await ws.send(encode("paired", token=token, server=self.store.device))
                self.notify(f"Teléfono vinculado: {name}. Ya puedes conectar.")
                await ws.close()
                return
            if hello["type"] != "hello" or not self.store.authenticate(peer, hello.get("token")):
                raise ProtocolError("Dispositivo no autorizado")
            if peer in self.sessions:
                await self.sessions[peer].close(4000, "Nueva conexión")
            supports_files = self.files is not None and CAPABILITY in hello.get("capabilities", [])
            relay = "hub-v2" in hello.get("capabilities", [])
            if not relay:
                self.store.skip_relays(peer)
            await ws.send(encode("welcome", server=self.store.device,
                                 capabilities=([CAPABILITY] if self.files else []) + ["hub-v2"]))
            if relay and self.settings_getter:
                await ws.send(encode("settings", **self.settings_getter()))
            for item in self.store.pending(8, peer):
                if item["origin"] != self.store.device and not relay:
                    continue
                await ws.send(encode("item", item=item, live=False,
                                     result=self.store.remote_result(item["id"])))
            await ws.send(encode("ready"))
            self.sessions[peer] = ws
            if relay:
                self.relay_peers.add(ws)
            if supports_files:
                self.file_peers.add(ws)
                self.file_last[ws] = {}
            self.notify("Teléfono conectado.")
            await self.broadcast_devices()
            retry_task = asyncio.create_task(self.retry(ws))
            async for raw in ws:
                msg = decode(raw)
                try:
                    if msg["type"] == "ready":
                        if supports_files:
                            await self.offer_files(ws)
                    elif msg["type"].startswith("file_") and supports_files:
                        await self.file_message(ws, msg, peer)
                    elif msg["type"] == "item":
                        fresh = self.store.receive(msg.get("item"), peer)
                        item = msg["item"]
                        await ws.send(encode("ack", id=item["id"]))
                        if fresh:
                            self.notify(f"Texto recibido: {item['id'][:8]} ({len(item['text'])} caracteres)")
                            if self.on_text_received:
                                self.on_text_received(item, peer)
                            for other, recipient in list(self.sessions.items()):
                                if other != peer and recipient not in self.relay_peers:
                                    self.store.skip_relays(other)
                                if other != peer and recipient in self.relay_peers:
                                    with contextlib.suppress(ConnectionClosed):
                                        await recipient.send(encode("item", item=item, live=True))
                            if self.auto_receive and self.clipboard:
                                try:
                                    self.clipboard.write(item["text"])
                                except (OSError, ValueError, RuntimeError) as exc:
                                    self.notify(f"Guardado en dock; no se pudo copiar: {exc}")
                    elif msg["type"] == "ack":
                        self.store.acknowledge(identifier(msg.get("id")), peer)
                    elif msg["type"] == "settings_update" and relay:
                        if self.settings_updater:
                            try:
                                await self.settings_updater(msg, peer)
                            except ProtocolError:
                                await ws.send(encode("settings_conflict", **self.settings_getter()))
                        else:
                            await ws.send(encode("settings_conflict", revision=0,
                                                 values=dict(image=False, text_mode="none")))
                    else:
                        raise ProtocolError("Tipo de mensaje desconocido")
                except ProtocolError as exc:
                    await ws.send(encode("error", message=str(exc)))
        except (ProtocolError, asyncio.TimeoutError) as exc:
            with contextlib.suppress(ConnectionClosed):
                await ws.send(encode("error", message=str(exc) or "Tiempo de autenticación agotado"))
                await ws.close(4001, "Solicitud rechazada")
        except ConnectionClosed:
            pass
        finally:
            self.relay_peers.discard(ws)
            self.file_peers.discard(ws)
            self.file_last.pop(ws, None)
            if retry_task:
                retry_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, ConnectionClosed):
                    await retry_task
            if peer and self.sessions.get(peer) is ws:
                del self.sessions[peer]
                self.notify("Teléfono desconectado; los envíos manuales quedarán pendientes.")
                await self.broadcast_devices()

    async def retry(self, ws):
        while True:
            await asyncio.sleep(5)
            peer = next((name for name, session in self.sessions.items() if session is ws), None)
            for item in self.store.pending(8, peer) if peer else []:
                if item["origin"] != self.store.device and ws not in self.relay_peers:
                    continue
                await ws.send(encode("item", item=item, live=False,
                                     result=self.store.remote_result(item["id"])))
            if ws in self.file_peers:
                await self.offer_files(ws)

    async def offer_files(self, ws):
        peer = next((name for name, session in self.sessions.items() if session is ws), None)
        if peer is None:
            return
        self.files.subscribe_peer(peer, ws in self.relay_peers)
        for msg in self.files.notices() + self.files.offers(peer):
            await ws.send(json.dumps(msg))

    async def file_message(self, ws, msg, peer):
        try:
            previous_state = None
            if msg["type"] in ("file_offer", "file_chunk"):
                raw_id = msg.get("file", {}).get("id") if msg["type"] == "file_offer" and isinstance(msg.get("file"), dict) else msg.get("id")
                with contextlib.suppress(ProtocolError):
                    previous_state = self.files.get(raw_id)["state"]
            reply = self.files.handle(msg, peer)
            if (reply and reply["type"] == "file_done" and msg["type"] in ("file_offer", "file_chunk")
                    and previous_state != "delivered" and self.on_file_received):
                self.on_file_received(reply["id"], peer)
            if reply and reply["type"] == "file_done" and msg["type"] in ("file_offer", "file_chunk"):
                for other in list(self.file_peers):
                    if other is not ws and other in self.relay_peers:
                        with contextlib.suppress(ConnectionClosed):
                            await self.offer_files(other)
            if reply:
                if reply["type"] == "file_chunk":
                    key = (reply["id"], reply["offset"])
                    if self.file_last[ws].get("chunk") == key:
                        return
                    self.file_last[ws]["chunk"] = key
                await ws.send(json.dumps(reply))
            if msg["type"] in ("file_done", "file_error", "file_cancelled"):
                self.notify("Archivo: consulta files para ver su estado.")
                await self.offer_files(ws)
        except (ValueError, OSError) as exc:
            raw_file = msg.get("file")
            id = msg.get("id") or (raw_file.get("id") if isinstance(raw_file, dict) else None)
            try:
                identifier(id)
            except ProtocolError:
                return
            self.files.fail_receiving(id, exc)
            await ws.send(encode("file_error", id=id, message=str(exc)[:200]))
            self.notify(f"Archivo rechazado: {str(exc)[:200]}")

    async def add_file(self, path, watched=None):
        if not self.files:
            raise ProtocolError("Dock de archivos no habilitado")
        self.files.capacity(path.stat().st_size)
        item = await asyncio.to_thread(self.files.prepare, path, watched[1] if watched else None)
        self.files.commit_prepared(item, watched)
        self.notify(f"Archivo preparado: {item['id'][:8]} ({item['size']} bytes)")
        for ws in list(self.file_peers):
            with contextlib.suppress(ConnectionClosed):
                await self.offer_files(ws)
        return item

    async def watch_files(self, stop=None):
        observed = {}
        reported = {}
        while stop is None or not stop.is_set():
            await asyncio.sleep(1)
            if stop is not None and stop.is_set():
                break
            if not self.files:
                continue
            present = set()
            for path in self.files.inbox.iterdir():
                if stop is not None and stop.is_set():
                    break
                if path.is_symlink() or not path.is_file() or path.suffix.lower() in (".part", ".tmp", ".crdownload"):
                    continue
                key = str(path); present.add(key)
                try:
                    stat = path.stat(); signature = f"{stat.st_size}:{stat.st_mtime_ns}"
                    old = self.files.db.execute("SELECT signature FROM watched WHERE path=?", (key,)).fetchone()
                    if old and old[0] == signature:
                        continue
                    if observed.get(key) != signature:
                        observed[key] = signature
                        continue
                    await self.add_file(path, (key, signature))
                    reported.pop(key, None)
                except (OSError, ValueError) as exc:
                    if reported.get(key) != str(exc):
                        self.notify(f"No se pudo incorporar {path.name}: {exc}")
                        reported[key] = str(exc)
            observed = {k: v for k, v in observed.items() if k in present}

    async def publish(self, text):
        item = self.store.create(text)
        for ws in list(self.sessions.values()):
            with contextlib.suppress(ConnectionClosed):
                await ws.send(encode("item", item=item, live=True))
        self.notify(f"Texto guardado: {item['id'][:8]} ({len(text)} caracteres)")
        return item

    async def broadcast_settings(self):
        if not self.settings_getter:
            return
        message = encode("settings", **self.settings_getter())
        for ws in list(self.relay_peers):
            with contextlib.suppress(ConnectionClosed):
                await ws.send(message)

    async def broadcast_devices(self):
        peers = self.store.peers()
        devices = [dict(id=self.store.device, name="Cerebro", connected=True, brain=True)] + [
            dict(id=row["id"], name=row["name"], connected=row["id"] in self.sessions, brain=False)
            for row in peers]
        message = encode("devices", items=devices)
        for ws in list(self.relay_peers):
            with contextlib.suppress(ConnectionClosed):
                await ws.send(message)

    async def send_ai_status(self, peer, source_id, action, state):
        ws = self.sessions.get(peer)
        if ws in self.relay_peers:
            with contextlib.suppress(ConnectionClosed):
                await ws.send(encode("ai_status", source_id=source_id, action=action, state=state))

    async def publish_existing(self, item_id):
        item = self.store.enqueue(item_id)
        result = self.store.remote_result(item_id)
        for ws in list(self.sessions.values()):
            with contextlib.suppress(ConnectionClosed):
                await ws.send(encode("item", item=item, live=True, result=result))
        return item

    async def revoke(self, peer):
        removed = self.store.revoke(peer)
        if removed and self.files:
            self.files.revoke_peer(peer)
        ws = self.sessions.get(peer)
        if ws:
            await ws.close(4003, "Vinculación revocada")
        if removed:
            await self.broadcast_devices()
        return removed

    def listen(self, host, port, context):
        return serve(self.handler, host, port, ssl=context, max_size=MAX_MESSAGE,
                     compression=None, ping_interval=20, ping_timeout=20)

    async def watch(self):
        if getattr(self.clipboard, "event_driven", False):
            return  # The Qt bridge publishes each external change, including copies made offline.
        while True:
            await asyncio.sleep(0.4)
            if not self.clipboard:
                continue
            try:
                if not self.auto_send or not self.sessions:
                    self.clipboard._last = self.clipboard.revision()
                    continue
                text = self.clipboard.changed()
                if text and not getattr(self, "ai_text_active", False):
                    await self.publish(text)
            except (OSError, RuntimeError, ValueError) as exc:
                if self.auto_send:
                    self.notify(f"Portapapeles: {exc}")
