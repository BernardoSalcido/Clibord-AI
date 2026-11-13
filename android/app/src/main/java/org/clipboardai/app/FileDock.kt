package org.clipboardai.app

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.util.Base64
import org.json.JSONObject
import java.io.File
import java.io.InputStream
import java.io.RandomAccessFile
import java.nio.CharBuffer
import java.security.MessageDigest
import java.time.Instant
import java.util.UUID

data class DockFile(val item: JSONObject, val direction: String, val state: String,
                    val offset: Long, val path: String, val error: String, val notice: Boolean) {
    val id: String get() = item.getString("id")
    val size: Long get() = item.getLong("size")
}

/** Separate additive database; old text history and pairing need no migration. */
class FileDock(context: Context, private val device: String) : SQLiteOpenHelper(context, "files.db", null, 2) {
    val root = File(context.filesDir, "dock-files").apply { mkdirs() }
    val received = File(root, "received").apply { mkdirs() }
    private val internal = File(root, "internal").apply { mkdirs() }

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("""CREATE TABLE files(id TEXT PRIMARY KEY, meta TEXT NOT NULL,
            direction TEXT NOT NULL, state TEXT NOT NULL, offset INTEGER NOT NULL DEFAULT 0,
            path TEXT NOT NULL, error TEXT NOT NULL DEFAULT '', notice INTEGER NOT NULL DEFAULT 0,
            hidden INTEGER NOT NULL DEFAULT 0)""")
        db.execSQL("CREATE TABLE cancelled(id TEXT PRIMARY KEY, peer TEXT NOT NULL)")
    }
    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        if (oldVersion < 2) db.execSQL("ALTER TABLE files ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")
    }

    @Synchronized fun recover() {
        val known = readableDatabase.rawQuery("SELECT id FROM files", null).use { cursor ->
            buildSet { while (cursor.moveToNext()) add(cursor.getString(0)) }
        }
        internal.listFiles()?.filter { it.extension in listOf("stage", "part", "blob") && it.nameWithoutExtension !in known &&
            it.lastModified() < System.currentTimeMillis() - 86_400_000L }
            ?.forEach { it.delete() }
    }

    @Synchronized fun history(): List<DockFile> = readableDatabase.rawQuery(
        "SELECT * FROM files WHERE state!='deleted' AND hidden=0 ORDER BY rowid DESC LIMIT 100", null).use { cursor ->
        buildList {
            while (cursor.moveToNext()) {
                fun text(key: String) = cursor.getString(cursor.getColumnIndexOrThrow(key))
                add(DockFile(JSONObject(text("meta")), text("direction"), text("state"),
                    cursor.getLong(cursor.getColumnIndexOrThrow("offset")), text("path"), text("error"),
                    cursor.getInt(cursor.getColumnIndexOrThrow("notice")) == 1))
            }
        }
    }
    @Synchronized fun get(id: String): DockFile {
        Wire.uuid(id)
        return readableDatabase.rawQuery("SELECT * FROM files WHERE id=?", arrayOf(id)).use { c ->
            require(c.moveToFirst()) { "Archivo no encontrado" }
            fun text(key: String) = c.getString(c.getColumnIndexOrThrow(key))
            DockFile(JSONObject(text("meta")), text("direction"), text("state"), c.getLong(c.getColumnIndexOrThrow("offset")),
                text("path"), text("error"), c.getInt(c.getColumnIndexOrThrow("notice")) == 1)
        }
    }
    private fun exists(id: String) = readableDatabase.rawQuery("SELECT 1 FROM files WHERE id=?", arrayOf(id)).use { it.moveToFirst() }
    private fun update(id: String, values: ContentValues) { writableDatabase.update("files", values, "id=?", arrayOf(id)) }
    private fun state(id: String, value: String, error: String = "") = update(id,
        ContentValues().apply { put("state", value); put("error", error.take(200)) })
    @Synchronized fun failReceiving(id: String, error: String) {
        writableDatabase.execSQL("UPDATE files SET state='error',error=? WHERE id=? AND state='receiving'", arrayOf(error.take(200), id))
    }

    @Synchronized fun capacity(size: Long) {
        var used = 0L
        readableDatabase.rawQuery("SELECT meta FROM files WHERE state NOT IN ('cancelled','deleted')", null).use { c ->
            while (c.moveToNext()) used += JSONObject(c.getString(0)).getLong("size")
        }
        require(used + size <= QUOTA) { "Dock lleno: límite 1 GiB. Borra archivos entregados." }
        val pending = readableDatabase.rawQuery("SELECT COUNT(*) FROM files WHERE state IN ('pending','sending','receiving')", null)
            .use { it.moveToFirst(); it.getInt(0) }
        require(pending < 100) { "Hay 100 transferencias pendientes" }
        require(root.usableSpace >= size + CHUNK) { "No hay espacio libre para el archivo" }
    }

    /** Runs on the import executor, not the socket worker; does not touch SQLite. */
    fun prepare(input: InputStream, name: String, mime: String): JSONObject {
        val id = UUID.randomUUID().toString()
        val item = metadata(JSONObject().put("id", id).put("origin", device).put("name", name)
            .put("created", Instant.now().toString()).put("size", 0).put("sha256", "0".repeat(64)).put("mime", mime), device)
        val stage = File(internal, "$id.stage")
        try {
            val hash = MessageDigest.getInstance("SHA-256")
            var total = 0L
            input.use { src -> stage.outputStream().use { dst ->
                val buffer = ByteArray(CHUNK)
                while (true) {
                    val count = src.read(buffer)
                    if (count < 0) break
                    if (count == 0) continue
                    total += count
                    require(total <= MAX_FILE) { "El archivo supera 100 MiB" }
                    require(root.usableSpace >= count + CHUNK) { "No hay espacio libre para el archivo" }
                    hash.update(buffer, 0, count); dst.write(buffer, 0, count)
                }
                dst.flush(); dst.fd.sync()
            } }
            return item.put("size", total).put("sha256", hex(hash.digest()))
        } catch (e: Exception) { stage.delete(); throw e }
    }

    @Synchronized fun commitPrepared(item: JSONObject): JSONObject {
        val id = item.getString("id")
        val stage = File(internal, "$id.stage"); val blob = File(internal, "$id.blob")
        try {
            capacity(item.getLong("size"))
            check(stage.renameTo(blob)) { "No se pudo guardar la copia de envío" }
            insert(item, "out", "pending", blob)
            return item
        } catch (e: Exception) { stage.delete(); blob.delete(); throw e }
    }

    private fun insert(item: JSONObject, direction: String, state: String, path: File) {
        writableDatabase.insertOrThrow("files", null, ContentValues().apply {
            put("id", item.getString("id")); put("meta", item.toString()); put("direction", direction)
            put("state", state); put("path", path.absolutePath)
        })
    }

    @Synchronized fun offers(): List<JSONObject> = readableDatabase.rawQuery(
        "SELECT meta FROM files WHERE direction='out' AND state IN ('pending','sending') ORDER BY rowid LIMIT 1", null
    ).use { c -> if (c.moveToFirst()) listOf(Wire.message("file_offer").put("file", JSONObject(c.getString(0)))) else emptyList() }
    @Synchronized fun notices(): List<JSONObject> = readableDatabase.rawQuery("SELECT id FROM files WHERE notice=1", null).use { c ->
        buildList { while (c.moveToNext()) add(Wire.message("file_cancel").put("id", c.getString(0))) }
    }
    private fun reply(type: String, id: String, offset: Long? = null) = Wire.message(type).put("id", id).apply {
        if (offset != null) put("offset", offset)
    }

    private fun accept(raw: JSONObject, peer: String, relayed: Boolean = false): JSONObject {
        val item = metadata(raw, if (relayed) null else peer); val id = item.getString("id")
        val cancelled = readableDatabase.rawQuery("SELECT peer FROM cancelled WHERE id=?", arrayOf(id)).use {
            if (it.moveToFirst()) it.getString(0) else null
        }
        if (cancelled != null) {
            require(cancelled == peer) { "Archivo no autorizado" }
            return reply("file_cancel", id)
        }
        if (exists(id)) {
            val old = get(id)
            require(old.direction == "in" && old.item.toString() == item.toString()) { "Identificador de archivo reutilizado" }
            if (old.state in listOf("delivered", "deleted")) return reply("file_done", id)
            if (old.state == "cancelled") return reply("file_cancel", id)
            require(old.state != "error") { old.error }
        } else {
            val busy = readableDatabase.rawQuery("SELECT 1 FROM files WHERE direction='in' AND state='receiving'", null)
                .use { it.moveToFirst() }
            require(!busy) { "Ya hay un archivo en recepción" }
            capacity(item.getLong("size"))
            insert(item, "in", "receiving", File(internal, "$id.part"))
        }
        val row = get(id); val part = File(row.path)
        val final = File(File(received, id), item.getString("name"))
        if (final.isFile && final.length() == row.size && digest(final) == item.getString("sha256")) {
            update(id, ContentValues().apply { put("state", "delivered"); put("offset", row.size); put("path", final.absolutePath) })
            return reply("file_done", id)
        }
        val offset = minOf(row.offset, if (part.exists()) part.length() else 0L)
        RandomAccessFile(part, "rw").use { it.setLength(offset) }
        update(id, ContentValues().apply { put("offset", offset) })
        return if (offset == row.size) complete(id) else reply("file_accept", id, offset)
    }

    private fun complete(id: String): JSONObject {
        val row = get(id); val part = File(row.path)
        if (part.length() != row.size || digest(part) != row.item.getString("sha256")) {
            val error = "El archivo no coincide con su huella; cancela y vuelve a enviarlo"
            state(id, "error", error); throw IllegalArgumentException(error)
        }
        val folder = File(received, id).apply { mkdirs() }
        val final = File(folder, row.item.getString("name"))
        check(part.renameTo(final)) { "No se pudo completar el archivo" }
        update(id, ContentValues().apply { put("state", "delivered"); put("path", final.absolutePath) })
        return reply("file_done", id)
    }

    private fun chunk(msg: JSONObject, peer: String, relayed: Boolean = false): JSONObject {
        val row = get(Wire.uuid(msg.getString("id")))
        require(row.direction == "in" && (relayed || row.item.getString("origin") == peer)) { "Archivo no autorizado" }
        if (row.state in listOf("delivered", "deleted")) return reply("file_done", row.id)
        if (row.state == "cancelled") return reply("file_cancel", row.id)
        require(row.state == "receiving") { "El archivo no está en recepción" }
        val offset = integer(msg, "offset"); val encoded = msg.getString("data")
        require(encoded.length <= 4 * ((CHUNK + 2) / 3) && encoded.matches(Regex("[A-Za-z0-9+/]*={0,2}"))) { "Fragmento inválido" }
        val data = Base64.decode(encoded, Base64.NO_WRAP)
        require(data.isNotEmpty() && data.size <= CHUNK && offset >= 0 && offset <= row.size - data.size) { "Fragmento fuera de límites" }
        RandomAccessFile(File(row.path), "rw").use { file ->
            if (offset < row.offset) {
                require(offset + data.size <= row.offset) { "Fragmento duplicado diferente" }
                val previous = ByteArray(data.size); file.seek(offset); file.readFully(previous)
                require(previous.contentEquals(data)) { "Fragmento duplicado diferente" }
                return reply("file_accept", row.id, row.offset)
            }
            require(offset == row.offset) { "Posición de archivo incorrecta" }
            file.seek(offset); file.write(data); file.fd.sync()
        }
        val next = offset + data.size
        update(row.id, ContentValues().apply { put("offset", next) })
        return if (next == row.size) complete(row.id) else reply("file_accept", row.id, next)
    }

    private fun sendChunk(msg: JSONObject): JSONObject? {
        val row = get(msg.getString("id"))
        if (row.direction != "out" || row.state !in listOf("pending", "sending")) return null
        val offset = integer(msg, "offset")
        require(offset >= 0 && offset < row.size) { "Posición de archivo incorrecta" }
        val data = ByteArray(minOf(CHUNK.toLong(), row.size - offset).toInt())
        RandomAccessFile(File(row.path), "r").use { it.seek(offset); it.readFully(data) }
        update(row.id, ContentValues().apply { put("state", "sending"); put("offset", offset) })
        return reply("file_chunk", row.id, offset).put("data", Base64.encodeToString(data, Base64.NO_WRAP))
    }

    @Synchronized fun cancel(id: String, notify: Boolean = true) {
        val row = get(id)
        if (row.state in listOf("delivered", "deleted")) return
        update(id, ContentValues().apply { put("state", "cancelled"); put("notice", if (notify) 1 else 0) })
        File(row.path).delete()
    }
    @Synchronized fun delete(id: String) {
        val row = get(id)
        require(row.state in listOf("delivered", "cancelled", "error")) { "Cancela primero el archivo pendiente" }
        if (row.state == "error") { cancel(id); return }
        File(row.path).delete()
        if (row.state == "delivered") state(id, "deleted")
        else if (row.state == "cancelled") {
            update(id, ContentValues().apply { put("hidden", 1) })
        }
    }
    @Synchronized fun deliveredUsage(): Pair<Int, Long> = readableDatabase.rawQuery("SELECT meta FROM files WHERE state='delivered'", null).use { c ->
        var count = 0; var bytes = 0L
        while (c.moveToNext()) { count++; bytes += JSONObject(c.getString(0)).getLong("size") }
        count to bytes
    }
    @Synchronized fun clearDelivered() {
        val ids = readableDatabase.rawQuery("SELECT id FROM files WHERE state='delivered'", null).use { c ->
            buildList { while (c.moveToNext()) add(c.getString(0)) }
        }
        ids.forEach { delete(it) }
    }
    @Synchronized fun handle(msg: JSONObject, peer: String, relayed: Boolean = false): JSONObject? {
        val kind = msg.getString("type")
        if (kind == "file_offer") return accept(msg.getJSONObject("file"), peer, relayed)
        if (kind == "file_chunk") return chunk(msg, peer, relayed)
        val id = Wire.uuid(msg.getString("id"))
        if (!exists(id) && kind in listOf("file_error", "file_cancelled")) return null
        if (kind == "file_cancel" && !exists(id)) {
            writableDatabase.execSQL("INSERT OR IGNORE INTO cancelled VALUES (?,?)", arrayOf(id, peer))
            return reply("file_cancelled", id)
        }
        val row = get(id)
        require(row.direction == "out" || relayed || row.item.getString("origin") == peer) { "Archivo no autorizado" }
        when (kind) {
            "file_accept" -> return sendChunk(msg)
            "file_done" -> if (row.direction == "out" && row.state in listOf("pending", "sending")) {
                update(id, ContentValues().apply { put("state", "delivered"); put("offset", row.size) })
            }
            "file_cancel" -> { cancel(id, false); return reply("file_cancelled", id) }
            "file_cancelled" -> update(id, ContentValues().apply { put("notice", 0) })
            "file_error" -> if (row.state !in listOf("delivered", "deleted", "cancelled")) state(id, "error", msg.optString("message", "Error de archivo"))
            else -> throw IllegalArgumentException("Acción de archivo desconocida")
        }
        return null
    }

    companion object {
        const val CAPABILITY = "files-v1"
        const val CHUNK = 64 * 1024
        const val MAX_FILE = 100L * 1024 * 1024
        const val QUOTA = 1024L * 1024 * 1024
        private fun hex(bytes: ByteArray) = bytes.joinToString("") { "%02x".format(it.toInt() and 255) }
        fun digest(file: File): String {
            val hash = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val buffer = ByteArray(CHUNK)
                while (true) { val count = input.read(buffer); if (count < 0) break; hash.update(buffer, 0, count) }
            }
            return hex(hash.digest())
        }
        private fun integer(item: JSONObject, key: String): Long {
            val value = item.get(key)
            require(value is Int || value is Long) { "Número de archivo inválido" }
            return item.getLong(key)
        }
        fun metadata(raw: JSONObject, origin: String?): JSONObject {
            val item = JSONObject()
            listOf("id", "origin", "created", "name", "size", "sha256", "mime").forEach { item.put(it, raw.get(it)) }
            Wire.uuid(item.getString("id"))
            val source = Wire.uuid(item.getString("origin"))
            require(origin == null || source == origin) { "Origen de archivo incorrecto" }
            val name = item.getString("name")
            val length = Charsets.UTF_8.newEncoder().encode(CharBuffer.wrap(name)).remaining()
            require(name.isNotEmpty() && length <= 240 && name !in listOf(".", "..") &&
                name.none { it in "/\\:<>\"|?*" || it.code < 32 || it.code == 127 } && !name.endsWith(".") && !name.endsWith(" ") &&
                !Regex("^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\\.|$)", RegexOption.IGNORE_CASE).containsMatchIn(name)) { "Nombre de archivo no admitido" }
            require(integer(item, "size") in 0..MAX_FILE) { "El archivo supera 100 MiB o tiene tamaño inválido" }
            require(Regex("[a-f0-9]{64}").matches(item.getString("sha256"))) { "Huella de archivo inválida" }
            require(item.getString("created").length <= 64 && item.getString("mime").length <= 120) { "Datos de archivo inválidos" }
            return item
        }
    }
}
