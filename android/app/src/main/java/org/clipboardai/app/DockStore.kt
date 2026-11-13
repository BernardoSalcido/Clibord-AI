package org.clipboardai.app

import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import org.json.JSONObject
import java.time.Instant
import java.util.UUID
import java.security.MessageDigest

data class DockItem(val value: JSONObject, val delivered: Boolean)

class DockStore(context: Context) : SQLiteOpenHelper(context, "dock.db", null, 1) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execSQL("INSERT INTO meta VALUES ('device', '${UUID.randomUUID()}')")
        db.execSQL("INSERT INTO meta VALUES ('seq', '0')")
        db.execSQL("""CREATE TABLE items (pos INTEGER PRIMARY KEY AUTOINCREMENT,
            id TEXT UNIQUE NOT NULL, origin TEXT NOT NULL, seq INTEGER NOT NULL,
            created TEXT NOT NULL, text TEXT NOT NULL, delivered INTEGER NOT NULL,
            UNIQUE(origin, seq))""")
        db.execSQL("""CREATE TABLE receipts (id TEXT PRIMARY KEY, origin TEXT NOT NULL,
            seq INTEGER NOT NULL, digest TEXT NOT NULL, UNIQUE(origin, seq))""")
    }
    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit
    private fun meta(key: String): String = readableDatabase.rawQuery(
        "SELECT value FROM meta WHERE key=?", arrayOf(key)
    ).use { it.moveToFirst(); it.getString(0) }
    val device: String get() = meta("device")

    private fun row(cursor: Cursor): DockItem {
        val item = JSONObject()
        listOf("id", "origin", "created", "text").forEach {
            item.put(it, cursor.getString(cursor.getColumnIndexOrThrow(it)))
        }
        item.put("seq", cursor.getLong(cursor.getColumnIndexOrThrow("seq")))
        return DockItem(item, cursor.getInt(cursor.getColumnIndexOrThrow("delivered")) == 1)
    }
    private fun insert(item: JSONObject, delivered: Boolean) {
        val values = ContentValues().apply {
            listOf("id", "origin", "created", "text").forEach { put(it, item.getString(it)) }
            put("seq", item.getLong("seq")); put("delivered", if (delivered) 1 else 0)
        }
        writableDatabase.insertOrThrow("items", null, values)
    }
    private fun prune() {
        writableDatabase.execSQL("""DELETE FROM items WHERE delivered=1 AND pos NOT IN
            (SELECT pos FROM items WHERE delivered=1 ORDER BY pos DESC LIMIT 500)""")
    }
    @Synchronized fun create(text: String): JSONObject {
        val item = Wire.item(JSONObject().put("id", UUID.randomUUID().toString())
            .put("origin", device).put("seq", meta("seq").toLong() + 1)
            .put("created", Instant.now().toString()).put("text", text))
        val pendingCount = readableDatabase.rawQuery("SELECT COUNT(*) FROM items WHERE delivered=0", null)
            .use { it.moveToFirst(); it.getInt(0) }
        require(pendingCount < 500) { "Hay 500 envíos pendientes. Conecta antes de enviar más." }
        val db = writableDatabase
        db.beginTransaction()
        try {
            insert(item, false)
            db.execSQL("UPDATE meta SET value=? WHERE key='seq'", arrayOf(item.getLong("seq").toString()))
            prune(); db.setTransactionSuccessful()
        } finally { db.endTransaction() }
        return item
    }
    @Synchronized fun receive(raw: JSONObject, server: String, relayed: Boolean = false): Boolean {
        val item = Wire.item(raw, if (relayed) null else server)
        val origin = item.getString("origin")
        require(origin != device) { "El cerebro devolvió una entrada propia" }
        val digest = MessageDigest.getInstance("SHA-256").digest(item.toString().toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it.toInt() and 255) }
        readableDatabase.rawQuery("SELECT * FROM receipts WHERE id=? OR (origin=? AND seq=?)",
            arrayOf(item.getString("id"), origin, item.getLong("seq").toString())).use {
            if (it.moveToFirst()) {
                require(it.getString(it.getColumnIndexOrThrow("id")) == item.getString("id") &&
                    it.getString(it.getColumnIndexOrThrow("origin")) == origin &&
                    it.getLong(it.getColumnIndexOrThrow("seq")) == item.getLong("seq") &&
                    it.getString(it.getColumnIndexOrThrow("digest")) == digest) {
                    "Identificador o secuencia reutilizados"
                }
                return false
            }
        }
        val db = writableDatabase
        db.beginTransaction()
        try {
            db.execSQL("INSERT INTO receipts VALUES (?,?,?,?)", arrayOf(item.getString("id"), origin,
                item.getLong("seq"), digest))
            insert(item, true); prune(); db.setTransactionSuccessful()
        }
        finally { db.endTransaction() }
        return true
    }
    @Synchronized fun acknowledge(id: String) {
        Wire.uuid(id)
        val db = writableDatabase
        db.beginTransaction()
        try {
            db.execSQL("UPDATE items SET delivered=1 WHERE id=? AND origin=?", arrayOf(id, device))
            prune(); db.setTransactionSuccessful()
        } finally { db.endTransaction() }
    }
    @Synchronized fun pending(): List<JSONObject> = readableDatabase.rawQuery(
        "SELECT * FROM items WHERE delivered=0 ORDER BY pos LIMIT 8", null
    ).use { cursor -> buildList { while (cursor.moveToNext()) add(row(cursor).value) } }
    @Synchronized fun history(): List<DockItem> = readableDatabase.rawQuery(
        "SELECT * FROM items ORDER BY pos DESC LIMIT 50", null
    ).use { cursor -> buildList { while (cursor.moveToNext()) add(row(cursor)) } }
    @Synchronized fun delete(id: String) {
        writableDatabase.delete("items", "id=? AND delivered=1", arrayOf(id))
    }
    @Synchronized fun textUsage(): Pair<Int, Int> = readableDatabase.rawQuery(
        "SELECT COUNT(*), COALESCE(SUM(CASE WHEN delivered=0 THEN 1 ELSE 0 END),0) FROM items", null
    ).use { it.moveToFirst(); it.getInt(0) to it.getInt(1) }
    /** Keep receipts so a delayed retransmission cannot recreate erased local history. */
    @Synchronized fun clearTexts(): Int {
        val database = writableDatabase
        database.beginTransaction()
        try {
            val count = textUsage().first
            database.delete("items", null, null)
            database.setTransactionSuccessful()
            return count
        } finally { database.endTransaction() }
    }
}
