"""Bounded, durable file dock. Payloads never use remote names as internal paths."""
import base64
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import sqlite3
import uuid
import time
from datetime import datetime, timezone

from .protocol import ProtocolError, identifier

CHUNK = 64 * 1024
MAX_FILE = 100 * 1024 * 1024
QUOTA = 1024 * 1024 * 1024
CAPABILITY = "files-v1"


def metadata(raw, origin):
    if not isinstance(raw, dict):
        raise ProtocolError("Datos de archivo inválidos")
    result = {k: raw.get(k) for k in ("id", "origin", "created", "name", "size", "sha256", "mime")}
    identifier(result["id"])
    source = identifier(result["origin"])
    if origin is not None and source != origin:
        raise ProtocolError("Origen de archivo incorrecto")
    name = result["name"]
    if (not isinstance(name, str) or not name or len(name.encode("utf-8")) > 240
            or name in (".", "..") or any(c in name for c in '/\\:<>"|?*')
            or any(ord(c) < 32 or ord(c) == 127 for c in name) or name.endswith((".", " "))
            or re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", name, re.I)):
        raise ProtocolError("Nombre de archivo no admitido")
    if type(result["size"]) is not int or not 0 <= result["size"] <= MAX_FILE:
        raise ProtocolError("El archivo supera 100 MiB o tiene tamaño inválido")
    if not isinstance(result["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", result["sha256"]):
        raise ProtocolError("Huella de archivo inválida")
    for key, limit in (("created", 64), ("mime", 120)):
        if not isinstance(result[key], str) or len(result[key]) > limit:
            raise ProtocolError("Datos de archivo inválidos")
    return result


def digest(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class FileDock:
    def __init__(self, root, device):
        self.root = Path(root).resolve()
        self.device = device
        self.inbox = self.root / "Entrada"
        self.received = self.root / "Recibidos"
        self.captures = self.root / "Capturas"
        self.internal = self.root / "interno"
        for folder in (self.inbox, self.received, self.captures, self.internal):
            folder.mkdir(parents=True, exist_ok=True)
            if folder.is_symlink():
                raise ProtocolError("La carpeta del dock no puede ser un enlace")
        self.db = sqlite3.connect(self.root / "files.sqlite3")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS files(id TEXT PRIMARY KEY, meta TEXT NOT NULL,
                direction TEXT NOT NULL, state TEXT NOT NULL, offset INTEGER NOT NULL DEFAULT 0,
                path TEXT NOT NULL, error TEXT NOT NULL DEFAULT '', notice INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS watched(path TEXT PRIMARY KEY, signature TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS cancelled(id TEXT PRIMARY KEY, peer TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS file_deliveries(
                file_id TEXT NOT NULL, peer TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                PRIMARY KEY(file_id,peer));
        """)
        if "hidden" not in {r[1] for r in self.db.execute("PRAGMA table_info(files)")}:
            with self.db: self.db.execute("ALTER TABLE files ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")
        # Partials without a committed record were never acknowledged and can be discarded.
        known = {r[0] for r in self.db.execute("SELECT id FROM files")}
        for path in self.internal.iterdir():
            if path.suffix in (".stage", ".part", ".blob") and path.stem not in known and path.stat().st_mtime < time.time() - 86400:
                path.unlink()

    def used(self):
        return sum(json.loads(r[0])["size"] for r in self.db.execute(
            "SELECT meta FROM files WHERE state NOT IN ('cancelled','deleted')"))

    def capacity(self, size):
        if self.used() + size > QUOTA:
            raise ProtocolError("Dock lleno: límite 1 GiB. Borra archivos entregados.")
        if self.db.execute("SELECT COUNT(*) FROM files WHERE state IN ('pending','sending','receiving')").fetchone()[0] >= 100:
            raise ProtocolError("Hay 100 transferencias pendientes")
        if shutil.disk_usage(self.root).free < size + CHUNK:
            raise ProtocolError("No hay espacio libre para el archivo")

    def prepare(self, source, signature=None):
        """Filesystem only: called off the network event loop."""
        source = Path(source)
        if source.is_symlink() or not source.is_file():
            raise ProtocolError("Selecciona un archivo normal, no una carpeta o enlace")
        before = source.stat()
        if signature is not None and signature != f"{before.st_size}:{before.st_mtime_ns}":
            raise ProtocolError("El archivo cambió al copiarse; se reintentará")
        item = metadata(dict(id=str(uuid.uuid4()), origin=self.device,
            created=datetime.now(timezone.utc).isoformat(), name=source.name, size=before.st_size,
            sha256="0" * 64, mime=mimetypes.guess_type(source.name)[0] or "application/octet-stream"), self.device)
        stage = self.internal / (item["id"] + ".stage")
        try:
            count = 0
            hash_value = hashlib.sha256()
            with source.open("rb") as src, stage.open("xb") as dst:
                while chunk := src.read(CHUNK):
                    count += len(chunk)
                    if count > MAX_FILE:
                        raise ProtocolError("El archivo supera 100 MiB")
                    hash_value.update(chunk); dst.write(chunk)
                dst.flush(); os.fsync(dst.fileno())
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or count != before.st_size:
                raise ProtocolError("El archivo cambió al copiarse; se reintentará")
            item["sha256"] = hash_value.hexdigest()
            return item
        except BaseException:
            stage.unlink(missing_ok=True)
            raise

    def commit_prepared(self, item, watched=None):
        stage = self.internal / (item["id"] + ".stage")
        blob = self.internal / (item["id"] + ".blob")
        try:
            self.capacity(item["size"])
            stage.replace(blob)
            with self.db:
                self.db.execute("INSERT INTO files(id,meta,direction,state,path) VALUES (?,?,?,?,?)",
                    (item["id"], json.dumps(item), "out", "pending", str(blob)))
                if watched:
                    self.db.execute("INSERT OR REPLACE INTO watched VALUES (?,?)", watched)
            return item
        except BaseException:
            stage.unlink(missing_ok=True); blob.unlink(missing_ok=True)
            raise

    def add(self, source):
        return self.commit_prepared(self.prepare(source))

    def save_capture(self, image, share=True):
        """Keep a clipboard screenshot in Images, optionally queueing it for peers."""
        if not isinstance(image, bytes) or not image.startswith(b"\x89PNG\r\n\x1a\n") or not 0 < len(image) <= 8 * 1024 * 1024:
            raise ValueError("La captura no es un PNG válido para el dock.")
        size = len(image)
        if self.used() + size > QUOTA:
            raise ProtocolError("Dock lleno: libera espacio antes de guardar otra captura.")
        if shutil.disk_usage(self.root).free < size + CHUNK:
            raise ProtocolError("No hay espacio libre para guardar la captura.")
        created = datetime.now(timezone.utc)
        file_id = str(uuid.uuid4())
        name = f"Captura-{created:%Y%m%d-%H%M%S}-{file_id[:8]}.png"
        item = metadata(dict(id=file_id, origin=self.device, created=created.isoformat(),
            name=name, size=size, sha256=hashlib.sha256(image).hexdigest(), mime="image/png"), self.device)
        stage = self.internal / (file_id + ".stage")
        final = self.captures / name
        try:
            with stage.open("xb") as stream:
                stream.write(image)
                stream.flush(); os.fsync(stream.fileno())
            stage.replace(final)
            with self.db:
                self.db.execute("INSERT INTO files(id,meta,direction,state,offset,path) VALUES (?,?,?,?,?,?)",
                    (file_id, json.dumps(item), "out" if share else "local",
                     "pending" if share else "delivered", 0, str(final)))
            return item
        except BaseException:
            stage.unlink(missing_ok=True)
            final.unlink(missing_ok=True)
            raise

    def get(self, prefix):
        if not isinstance(prefix, str) or len(prefix) < 4:
            raise ProtocolError("Usa al menos cuatro caracteres del identificador")
        rows = self.db.execute("SELECT * FROM files WHERE substr(id,1,?)=?", (len(prefix), prefix)).fetchall()
        if len(rows) != 1:
            raise ProtocolError("Usa un identificador único de files")
        return dict(rows[0])

    def history(self):
        return [dict(r, item=json.loads(r["meta"])) for r in self.db.execute(
            "SELECT * FROM files WHERE state!='deleted' AND hidden=0 ORDER BY rowid DESC LIMIT 100")]

    def set_state(self, id, state, error=""):
        with self.db:
            self.db.execute("UPDATE files SET state=?,error=? WHERE id=?", (state, error[:200], id))

    def fail_receiving(self, id, error):
        with self.db:
            self.db.execute("UPDATE files SET state='error',error=? WHERE id=? AND state='receiving'", (str(error)[:200], id))

    def subscribe_peer(self, peer, relay=False):
        """Queue existing dock files for one recipient without resending acknowledged IDs."""
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO file_deliveries(file_id,peer) "
                "SELECT id,? FROM files WHERE direction='out' AND state NOT IN ('cancelled','deleted','error') "
                "AND (state IN ('pending','sending') OR id IN "
                "(SELECT id FROM files ORDER BY rowid DESC LIMIT 50))", (peer,))
            if relay:
                for row in self.db.execute("SELECT id,meta FROM files WHERE direction='in' AND state='delivered' "
                                           "ORDER BY rowid DESC LIMIT 50"):
                    if json.loads(row["meta"])["origin"] != peer:
                        self.db.execute("INSERT OR IGNORE INTO file_deliveries(file_id,peer) VALUES (?,?)",
                                        (row["id"], peer))

    def revoke_peer(self, peer):
        with self.db:
            self.db.execute("DELETE FROM file_deliveries WHERE peer=?", (peer,))
            self.db.execute("UPDATE files SET state='delivered' WHERE direction='out' "
                "AND state IN ('pending','sending') AND id NOT IN "
                "(SELECT file_id FROM file_deliveries WHERE state='pending') "
                "AND id IN (SELECT file_id FROM file_deliveries)")

    def offers(self, peer=None):
        if peer is not None:
            rows = self.db.execute("SELECT files.meta FROM files JOIN file_deliveries "
                "ON files.id=file_deliveries.file_id WHERE file_deliveries.peer=? "
                "AND file_deliveries.state='pending' AND files.state NOT IN ('cancelled','deleted','error') "
                "ORDER BY files.rowid LIMIT 1", (peer,)).fetchall()
            return [dict(v=1, type="file_offer", file=json.loads(r[0])) for r in rows]
        rows = self.db.execute("SELECT meta FROM files WHERE direction='out' AND state IN ('pending','sending') ORDER BY rowid LIMIT 1").fetchall()
        return [dict(v=1, type="file_offer", file=json.loads(r[0])) for r in rows]

    def notices(self):
        return [dict(v=1, type="file_cancel", id=r[0]) for r in self.db.execute("SELECT id FROM files WHERE notice=1")]

    def accept(self, raw, peer, relayed=False):
        item = metadata(raw, None if relayed else peer)
        id = item["id"]
        cancelled = self.db.execute("SELECT peer FROM cancelled WHERE id=?", (id,)).fetchone()
        if cancelled:
            if cancelled[0] != peer:
                raise ProtocolError("Archivo no autorizado")
            return dict(v=1, type="file_cancel", id=id)
        old = self.db.execute("SELECT * FROM files WHERE id=?", (id,)).fetchone()
        if old:
            if json.loads(old["meta"]) != item or old["direction"] != "in":
                raise ProtocolError("Identificador de archivo reutilizado")
            if old["state"] in ("delivered", "deleted"):
                return dict(v=1, type="file_done", id=id)
            if old["state"] == "cancelled":
                return dict(v=1, type="file_cancel", id=id)
            if old["state"] == "error":
                raise ProtocolError(old["error"])
        else:
            if self.db.execute("SELECT 1 FROM files WHERE direction='in' AND state='receiving'").fetchone():
                raise ProtocolError("Ya hay un archivo en recepción")
            self.capacity(item["size"])
            part = self.internal / (id + ".part")
            with self.db:
                self.db.execute("INSERT INTO files(id,meta,direction,state,path) VALUES (?,?,?,?,?)",
                    (id, json.dumps(item), "in", "receiving", str(part)))
        return self._resume(id)

    def _resume(self, id):
        row = self.get(id); item = json.loads(row["meta"])
        part = Path(row["path"])
        final = self.received / id / item["name"]
        # Recovery after atomic rename but before completion was committed.
        if final.is_file() and final.stat().st_size == item["size"] and digest(final) == item["sha256"]:
            with self.db:
                self.db.execute("UPDATE files SET state='delivered',offset=?,path=? WHERE id=?", (item["size"], str(final), id))
            return dict(v=1, type="file_done", id=id)
        offset = min(row["offset"], part.stat().st_size if part.exists() else 0)
        with part.open("r+b" if part.exists() else "wb") as stream:
            stream.truncate(offset)
        with self.db:
            self.db.execute("UPDATE files SET offset=? WHERE id=?", (offset, id))
        return self._completed(id) if offset == item["size"] else dict(v=1, type="file_accept", id=id, offset=offset)

    def _completed(self, id):
        row = self.get(id); item = json.loads(row["meta"]); part = Path(row["path"])
        if part.stat().st_size != item["size"] or digest(part) != item["sha256"]:
            self.set_state(id, "error", "El archivo no coincide con su huella; cancela y vuelve a enviarlo")
            raise ProtocolError("El archivo no coincide con su huella; cancela y vuelve a enviarlo")
        folder = self.received / id
        folder.mkdir(exist_ok=True)
        final = folder / item["name"]
        part.replace(final)
        with self.db:
            self.db.execute("UPDATE files SET state='delivered',path=? WHERE id=?", (str(final), id))
        return dict(v=1, type="file_done", id=id)

    def chunk(self, msg, peer, relayed=False):
        row = self.get(identifier(msg.get("id"))); item = json.loads(row["meta"])
        if row["direction"] != "in" or item["origin"] != peer and not relayed:
            raise ProtocolError("Archivo no autorizado")
        if row["state"] in ("delivered", "deleted"):
            return dict(v=1, type="file_done", id=item["id"])
        if row["state"] == "cancelled":
            return dict(v=1, type="file_cancel", id=item["id"])
        if row["state"] != "receiving":
            raise ProtocolError("El archivo no está en recepción")
        offset = msg.get("offset"); encoded = msg.get("data")
        if type(offset) is not int or offset < 0 or not isinstance(encoded, str) or len(encoded) > 4 * ((CHUNK + 2) // 3):
            raise ProtocolError("Fragmento inválido")
        try:
            data = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ProtocolError("Fragmento inválido") from exc
        if not data or len(data) > CHUNK or offset + len(data) > item["size"]:
            raise ProtocolError("Fragmento fuera de límites")
        path = Path(row["path"])
        with path.open("r+b") as stream:
            if offset < row["offset"]:
                stream.seek(offset)
                if offset + len(data) > row["offset"] or stream.read(len(data)) != data:
                    raise ProtocolError("Fragmento duplicado diferente")
                return dict(v=1, type="file_accept", id=item["id"], offset=row["offset"])
            if offset != row["offset"]:
                raise ProtocolError("Posición de archivo incorrecta")
            stream.seek(offset); stream.write(data); stream.flush(); os.fsync(stream.fileno())
        offset += len(data)
        with self.db:
            self.db.execute("UPDATE files SET offset=? WHERE id=?", (offset, item["id"]))
        return self._completed(item["id"]) if offset == item["size"] else dict(v=1, type="file_accept", id=item["id"], offset=offset)

    def send_chunk(self, msg, peer=None):
        row = self.get(identifier(msg.get("id"))); item = json.loads(row["meta"])
        if peer is not None and self.db.execute(
                "SELECT 1 FROM file_deliveries WHERE file_id=?", (item["id"],)).fetchone() and not self.db.execute(
                "SELECT 1 FROM file_deliveries WHERE file_id=? AND peer=? AND state='pending'",
                (item["id"], peer)).fetchone():
            raise ProtocolError("Archivo no ofrecido a este dispositivo")
        if row["direction"] == "in" and row["state"] != "delivered":
            return None
        if row["direction"] == "out" and row["state"] not in ("pending", "sending", "delivered"):
            return None
        offset = msg.get("offset")
        if type(offset) is not int or not 0 <= offset < item["size"]:
            raise ProtocolError("Posición de archivo incorrecta")
        with open(row["path"], "rb") as stream:
            stream.seek(offset); data = stream.read(min(CHUNK, item["size"] - offset))
        if not data:
            raise ProtocolError("La copia de envío no está disponible")
        if row["direction"] == "out" and row["state"] != "delivered":
            with self.db:
                self.db.execute("UPDATE files SET state='sending',offset=? WHERE id=?", (offset, item["id"]))
        return dict(v=1, type="file_chunk", id=item["id"], offset=offset, data=base64.b64encode(data).decode("ascii"))

    def done(self, id, peer=None):
        row = self.get(identifier(id)); item = json.loads(row["meta"])
        if peer is not None and self.db.execute("SELECT 1 FROM file_deliveries WHERE file_id=?", (id,)).fetchone():
            with self.db:
                self.db.execute("UPDATE file_deliveries SET state='acked' WHERE file_id=? AND peer=?", (id, peer))
                if row["direction"] == "out" and not self.db.execute(
                        "SELECT 1 FROM file_deliveries WHERE file_id=? AND state='pending'", (id,)).fetchone():
                    self.db.execute("UPDATE files SET state='delivered',offset=? WHERE id=?", (item["size"], id))
            return
        if row["direction"] == "out" and row["state"] in ("pending", "sending"):
            with self.db:
                self.db.execute("UPDATE files SET state='delivered',offset=? WHERE id=?", (item["size"], id))

    def cancel(self, prefix, notify=True):
        row = self.get(prefix)
        if row["state"] in ("delivered", "deleted"):
            return
        with self.db:
            self.db.execute("UPDATE files SET state='cancelled',notice=? WHERE id=?", (int(notify), row["id"]))
        Path(row["path"]).unlink(missing_ok=True)

    def delete(self, prefix):
        row = self.get(prefix)
        if row["state"] not in ("delivered", "cancelled", "error"):
            raise ProtocolError("Cancela primero el archivo pendiente")
        if row["state"] == "error":
            return self.cancel(prefix)
        Path(row["path"]).unlink(missing_ok=True)
        if row["state"] == "delivered":
            self.set_state(row["id"], "deleted")
        else:
            with self.db: self.db.execute("UPDATE files SET hidden=1 WHERE id=?", (row["id"],))

    def delivered_usage(self):
        sizes = [json.loads(r[0])["size"] for r in self.db.execute("SELECT meta FROM files WHERE state='delivered'")]
        return len(sizes), sum(sizes)

    def clear_delivered(self):
        ids = [r[0] for r in self.db.execute("SELECT id FROM files WHERE state='delivered'")]
        for id in ids: self.delete(id)

    def handle(self, msg, peer, relayed=False):
        kind = msg["type"]
        if kind == "file_offer": return self.accept(msg.get("file"), peer, relayed)
        if kind == "file_chunk": return self.chunk(msg, peer, relayed)
        id = identifier(msg.get("id"))
        exists = self.db.execute("SELECT 1 FROM files WHERE id=?", (id,)).fetchone()
        if not exists and kind == "file_cancel":
            with self.db:
                self.db.execute("INSERT OR IGNORE INTO cancelled VALUES (?,?)", (id, peer))
            return dict(v=1, type="file_cancelled", id=id)
        if not exists and kind in ("file_error", "file_cancelled"):
            return None
        row = self.get(id)
        relay_delivery = self.db.execute("SELECT 1 FROM file_deliveries WHERE file_id=? AND peer=?",
                                         (id, peer)).fetchone()
        if row["direction"] == "in" and json.loads(row["meta"])["origin"] != peer and not relay_delivery and not relayed:
            raise ProtocolError("Archivo no autorizado")
        if kind == "file_accept": return self.send_chunk(msg, peer)
        if kind == "file_done": self.done(id, peer)
        elif kind == "file_cancel":
            if relay_delivery:
                with self.db:
                    self.db.execute("UPDATE file_deliveries SET state='cancelled' WHERE file_id=? AND peer=?", (id, peer))
                return dict(v=1, type="file_cancelled", id=id)
            self.cancel(id, False)
            return dict(v=1, type="file_cancelled", id=id)
        elif kind == "file_cancelled":
            with self.db: self.db.execute("UPDATE files SET notice=0 WHERE id=?", (id,))
        elif kind == "file_error":
            if relay_delivery:
                with self.db:
                    self.db.execute("UPDATE file_deliveries SET state='error' WHERE file_id=? AND peer=?", (id, peer))
            elif row["state"] not in ("delivered", "deleted", "cancelled"):
                self.set_state(id, "error", str(msg.get("message", "Error de archivo")))
        else: raise ProtocolError("Acción de archivo desconocida")

    def close(self): self.db.close()
