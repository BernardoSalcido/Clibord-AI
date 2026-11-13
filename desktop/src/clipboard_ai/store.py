"""Durable inbox/outbox; all access is on the server event-loop thread."""
import hashlib
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone

from .protocol import ProtocolError, validate_item

LIMIT = 500
MAX_PEERS = 32


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS peers (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS items (
                pos INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                origin TEXT NOT NULL, seq INTEGER NOT NULL, created TEXT NOT NULL,
                text TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0,
                UNIQUE(origin, seq));
            CREATE TABLE IF NOT EXISTS receipts (
                id TEXT PRIMARY KEY, origin TEXT NOT NULL, seq INTEGER NOT NULL,
                digest TEXT NOT NULL, UNIQUE(origin, seq));
            CREATE TABLE IF NOT EXISTS deliveries (
                item_id TEXT NOT NULL, peer TEXT NOT NULL, acked INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(item_id, peer));
            CREATE TABLE IF NOT EXISTS ai_records (
                result_id TEXT PRIMARY KEY, action TEXT NOT NULL, source_text TEXT NOT NULL,
                source_image BLOB, stats TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS remote_ai_jobs (
                source_id TEXT PRIMARY KEY, state TEXT NOT NULL, result_id TEXT, error TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL DEFAULT 'image', source_text TEXT NOT NULL DEFAULT '', source_origin TEXT NOT NULL DEFAULT '');
        """)
        if not self.meta("device"):
            with self.db:
                self.db.execute("INSERT INTO meta VALUES ('device', ?)", (str(uuid.uuid4()),))
                self.db.execute("INSERT INTO meta VALUES ('seq', '0')")
        self.device = self.meta("device")
        columns = {r[1] for r in self.db.execute("PRAGMA table_info(remote_ai_jobs)")}
        for name, definition in (("mode", "TEXT NOT NULL DEFAULT 'image'"),
                                 ("source_text", "TEXT NOT NULL DEFAULT ''"),
                                 ("source_origin", "TEXT NOT NULL DEFAULT ''")):
            if name not in columns:
                with self.db: self.db.execute(f"ALTER TABLE remote_ai_jobs ADD COLUMN {name} {definition}")
        # Older databases only had one global delivered bit. Preserve its pending work.
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO meta VALUES ('settings_revision','0')")
            self.db.execute("INSERT OR IGNORE INTO deliveries(item_id,peer) "
                "SELECT items.id,peers.id FROM items CROSS JOIN peers "
                "WHERE items.delivered=0 AND items.origin=?", (self.device,))
            self.db.execute("UPDATE remote_ai_jobs SET state='pending' WHERE state='running'")

    def settings_revision(self):
        return int(self.meta("settings_revision"))

    def advance_settings(self):
        revision = self.settings_revision() + 1
        with self.db:
            self.db.execute("UPDATE meta SET value=? WHERE key='settings_revision'", (str(revision),))
        return revision

    def queue_remote_image(self, source_id, origin=""):
        with self.db:
            return self.db.execute("INSERT OR IGNORE INTO remote_ai_jobs(source_id,state,mode,source_origin) "
                                   "VALUES (?,'pending','image',?)", (source_id, origin)).rowcount > 0

    def queue_remote_text(self, source_id, origin, text, mode):
        with self.db:
            return self.db.execute("INSERT OR IGNORE INTO remote_ai_jobs(source_id,state,mode,source_origin,source_text) "
                                   "VALUES (?,'pending',?,?,?)", (source_id, mode, origin, text)).rowcount > 0

    def remote_image_jobs(self):
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM remote_ai_jobs WHERE state='pending' ORDER BY rowid")]

    def remote_result(self, result_id):
        row = self.db.execute("SELECT source_id,mode,source_origin FROM remote_ai_jobs WHERE result_id=?",
                              (result_id,)).fetchone()
        return dict(source_id=row[0], action=row[1], source_origin=row[2]) if row else None

    def remote_image_state(self, source_id, state, result_id=None, error=""):
        with self.db:
            self.db.execute("UPDATE remote_ai_jobs SET state=?,result_id=COALESCE(?,result_id),error=? WHERE source_id=?",
                            (state, result_id, error[:200], source_id))

    def meta(self, key):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def pair(self, peer, name):
        if self.db.execute("SELECT 1 FROM peers WHERE id=?", (peer,)).fetchone():
            raise ProtocolError("Dispositivo ya vinculado; revócalo antes de volver a vincular")
        if self.db.execute("SELECT COUNT(*) FROM peers").fetchone()[0] >= MAX_PEERS:
            raise ProtocolError("Máximo de 32 dispositivos vinculados")
        token = secrets.token_urlsafe(32)
        with self.db:
            self.db.execute("INSERT INTO peers VALUES (?, ?, ?)",
                            (peer, name[:80], hashlib.sha256(token.encode()).hexdigest()))
            self.db.execute("INSERT OR IGNORE INTO deliveries(item_id,peer) "
                "SELECT id,? FROM items WHERE delivered=0 OR pos IN "
                "(SELECT pos FROM items ORDER BY pos DESC LIMIT 50)", (peer,))
            self.db.execute("UPDATE items SET delivered=0 WHERE id IN "
                "(SELECT item_id FROM deliveries WHERE peer=? AND acked=0)", (peer,))
        return token

    def authenticate(self, peer, token):
        if not isinstance(token, str) or len(token) > 128:
            return False
        row = self.db.execute("SELECT token_hash FROM peers WHERE id=?", (peer,)).fetchone()
        return bool(row and secrets.compare_digest(row[0], hashlib.sha256(token.encode()).hexdigest()))

    def peers(self):
        return [dict(r) for r in self.db.execute("SELECT id,name FROM peers")]

    def revoke(self, peer):
        with self.db:
            removed = self.db.execute("DELETE FROM peers WHERE id=?", (peer,)).rowcount > 0
            self.db.execute("DELETE FROM deliveries WHERE peer=?", (peer,))
            self._refresh_delivered()
            return removed

    def skip_relays(self, peer):
        """Legacy clients understand only text originating at their paired computer."""
        with self.db:
            self.db.execute("UPDATE deliveries SET acked=1 WHERE peer=? AND item_id IN "
                            "(SELECT id FROM items WHERE origin!=?)", (peer, self.device))
            self._refresh_delivered()

    def _capacity(self):
        if self.db.execute("SELECT COUNT(*) FROM items WHERE delivered=0").fetchone()[0] >= LIMIT:
            raise ProtocolError("Hay 500 envíos pendientes. Conecta el teléfono antes de enviar más.")

    def create(self, text, local=False):
        seq = int(self.meta("seq")) + 1
        item = validate_item(dict(id=str(uuid.uuid4()), origin=self.device, seq=seq,
                                  created=datetime.now(timezone.utc).isoformat(), text=text))
        if not local:
            self._capacity()
        with self.db:
            self._insert(item, local)
            if not local:
                self.db.execute("INSERT INTO deliveries(item_id,peer) SELECT ?,id FROM peers", (item["id"],))
            self.db.execute("UPDATE meta SET value=? WHERE key='seq'", (str(seq),))
            self._prune()
        return item

    def ai_result(self, text, action, source, stats):
        item = self.create(text, local=True)
        with self.db:
            self.db.execute("INSERT INTO ai_records VALUES (?,?,?,?,?)", (item["id"], action,
                source.get("text", ""), source.get("image"), json.dumps(stats)))
            self.db.execute("DELETE FROM ai_records WHERE result_id NOT IN (SELECT id FROM items)")
            self.db.execute("DELETE FROM ai_records WHERE rowid NOT IN (SELECT rowid FROM ai_records ORDER BY rowid DESC LIMIT 20)")
            while self.db.execute("SELECT COALESCE(SUM(length(source_image)),0) FROM ai_records").fetchone()[0] > 64 * 1024 * 1024:
                self.db.execute("DELETE FROM ai_records WHERE rowid=(SELECT MIN(rowid) FROM ai_records)")
        return item

    def enqueue(self, item_id):
        row = self.get(item_id)
        if row["origin"] != self.device:
            raise ProtocolError("Solo se pueden publicar resultados locales")
        self._capacity()
        with self.db:
            self.db.execute("UPDATE items SET delivered=0 WHERE id=?", (item_id,))
            self.db.execute("INSERT INTO deliveries(item_id,peer,acked) "
                "SELECT ?,id,0 FROM peers WHERE true ON CONFLICT(item_id,peer) DO UPDATE SET acked=0", (item_id,))
        return self.wire(row)

    def _insert(self, item, delivered):
        self.db.execute("INSERT INTO items(id,origin,seq,created,text,delivered) VALUES (?,?,?,?,?,?)",
                        (*[item[k] for k in ("id", "origin", "seq", "created", "text")], int(delivered)))

    def receive(self, item, peer):
        item = validate_item(item, peer)
        digest = hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        old = self.db.execute("SELECT * FROM receipts WHERE id=? OR (origin=? AND seq=?)",
                              (item["id"], peer, item["seq"])).fetchone()
        if old:
            if old["id"] != item["id"] or old["origin"] != peer or old["seq"] != item["seq"] or old["digest"] != digest:
                raise ProtocolError("Identificador o secuencia reutilizados con contenido diferente")
            return False
        with self.db:
            self.db.execute("INSERT INTO receipts VALUES (?,?,?,?)", (item["id"], peer, item["seq"], digest))
            self._insert(item, True)
            self.db.execute("INSERT INTO deliveries(item_id,peer) SELECT ?,id FROM peers WHERE id!=?",
                            (item["id"], peer))
            self._refresh_delivered()
            self._prune()
        return True

    def _prune(self):
        self.db.execute("DELETE FROM items WHERE delivered=1 AND pos NOT IN "
                        "(SELECT pos FROM items WHERE delivered=1 ORDER BY pos DESC LIMIT ?)", (LIMIT,))
        self.db.execute("DELETE FROM ai_records WHERE result_id NOT IN (SELECT id FROM items)")
        self.db.execute("DELETE FROM deliveries WHERE item_id NOT IN (SELECT id FROM items)")

    def _refresh_delivered(self):
        self.db.execute("UPDATE items SET delivered=1 WHERE delivered=0 AND "
                        "NOT EXISTS (SELECT 1 FROM deliveries WHERE item_id=items.id AND acked=0) "
                        "AND EXISTS (SELECT 1 FROM deliveries WHERE item_id=items.id)")

    def acknowledge(self, item_id, peer=None):
        with self.db:
            if peer is None:
                self.db.execute("UPDATE deliveries SET acked=1 WHERE item_id=?", (item_id,))
                self.db.execute("UPDATE items SET delivered=1 WHERE id=? AND origin=?", (item_id, self.device))
            else:
                self.db.execute("UPDATE deliveries SET acked=1 WHERE item_id=? AND peer=?", (item_id, peer))
                self._refresh_delivered()
            self._prune()

    def pending(self, limit=500, peer=None):
        if peer is not None:
            return [self.wire(r) for r in self.db.execute(
                "SELECT items.* FROM items JOIN deliveries ON items.id=deliveries.item_id "
                "WHERE deliveries.peer=? AND deliveries.acked=0 ORDER BY items.pos LIMIT ?", (peer, limit))]
        return [self.wire(r) for r in self.db.execute("SELECT * FROM items WHERE delivered=0 ORDER BY pos LIMIT ?", (limit,))]

    def pending_count(self):
        return self.db.execute("SELECT COUNT(*) FROM items WHERE delivered=0").fetchone()[0]

    @staticmethod
    def wire(row):
        return {k: row[k] for k in ("id", "origin", "seq", "created", "text")}

    def history(self, limit=20):
        return [dict(r) for r in self.db.execute("SELECT items.*, ai_records.action AS ai_action "
            "FROM items LEFT JOIN ai_records ON items.id=ai_records.result_id ORDER BY items.pos DESC LIMIT ?", (limit,))]

    def get(self, prefix):
        if not isinstance(prefix, str) or len(prefix) < 4:
            raise ProtocolError("Usa al menos cuatro caracteres del identificador")
        rows = self.db.execute("SELECT * FROM items WHERE substr(id,1,?)=?", (len(prefix), prefix)).fetchall()
        if len(rows) != 1:
            raise ProtocolError("Usa un identificador único de la lista")
        return dict(rows[0])

    def delete(self, prefix):
        row = self.get(prefix)
        if not row["delivered"] and row["origin"] != self.device:
            raise ProtocolError("No se puede eliminar un elemento pendiente de otro dispositivo")
        with self.db:
            self.db.execute("DELETE FROM items WHERE id=?", (row["id"],))
            self.db.execute("DELETE FROM ai_records WHERE result_id=?", (row["id"],))

    def clear_texts(self):
        """Remove local text history and unsent texts; keep receipts for dedupe."""
        with self.db:
            count = self.db.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            self.db.execute("DELETE FROM ai_records")
            self.db.execute("DELETE FROM items")
        return count

    def close(self):
        self.db.close()
