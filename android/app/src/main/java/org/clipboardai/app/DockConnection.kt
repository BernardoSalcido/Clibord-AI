package org.clipboardai.app

import android.content.Context
import android.content.ClipData
import android.content.ClipboardManager
import android.os.Handler
import android.os.Looper
import android.net.Uri
import android.provider.OpenableColumns
import android.widget.Toast
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import org.json.JSONObject
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.io.File

/** All network and database actions are serialized, including retry and close. */
class DockConnection(context: Context, private val store: DockStore,
                     private val onStopped: () -> Unit = {},
                     private val update: (String) -> Unit) {
    private val prefs = context.getSharedPreferences("connection", Context.MODE_PRIVATE)
    private val shared = context.getSharedPreferences("shared_settings", Context.MODE_PRIVATE)
    private val app = context.applicationContext
    val files = FileDock(app, store.device).apply { recover() }
    private val importer = Executors.newSingleThreadExecutor()
    private var fileSupport = false
    private var hubSupport = false
    private var lastFileChunk: Pair<String, Long>? = null
    private var lastFileUpdate = 0L
    private val worker = Executors.newSingleThreadScheduledExecutor()
    private val main = Handler(Looper.getMainLooper())
    private var socket: WebSocket? = null
    private var client: OkHttpClient? = null
    @Volatile private var generation = 0
    @Volatile private var active = false
    private var ready = false
    private var connecting = false
    private var retrySeconds = 1L
    private var server = ""
    private var pairing = false
    private var deviceInfo = org.json.JSONArray().toString()

    init {
        worker.scheduleWithFixedDelay({
            try {
                if (ready) { store.pending().forEach { sendItem(it, false) }; offerFiles() }
            } catch (e: Exception) { status(e.message ?: "No se pudo reintentar el envío") }
        }, 5, 5, TimeUnit.SECONDS)
    }
    private fun execute(action: () -> Unit) {
        try { worker.execute(action) }
        catch (_: java.util.concurrent.RejectedExecutionException) { /* Service already destroyed. */ }
    }
    private fun status(text: String) { main.post { update(text) } }
    private fun halted(text: String) {
        active = false; ready = false
        status(text)
        val stoppedGeneration = generation
        main.post { if (generation == stoppedGeneration && !active) onStopped() }
    }
    fun hasCredentials() = prefs.contains("token")
    fun endpoint() = prefs.getString("host", "").orEmpty()
    fun endpointPort() = prefs.getInt("port", 45821)
    fun changeEndpoint(host: String, port: Int) = execute {
        if (!hasCredentials()) { status("Vincula primero el cerebro"); return@execute }
        check(prefs.edit().putString("host", host).putInt("port", port).commit()) {
            "No se pudo guardar la nueva dirección"
        }
        if (active) open(host, port, prefs.getString("fingerprint", "")!!, null)
        else status("Dirección guardada · pulsa Conectar")
    }

    fun pair(data: PairingData) = execute {
        open(data.host, data.port, data.fingerprint, data.code)
    }

    fun connect() = execute {
        if (!hasCredentials()) { halted("Primero vincula el ordenador"); return@execute }
        open(prefs.getString("host", "")!!, prefs.getInt("port", 45821),
            prefs.getString("fingerprint", "")!!, null)
    }

    private fun open(host: String, port: Int, fingerprint: String, code: String?) {
        stopSocket()
        connecting = true
        active = true
        pairing = code != null
        val current = generation
        ready = false
        status(if (pairing) "Vinculando…" else "Conectando…")
        try {
            client = PinnedTls.client(fingerprint)
            val address = if (host.contains(":")) "[$host]" else host
            socket = client!!.newWebSocket(Request.Builder().url("https://$address:$port/").build(),
                object : WebSocketListener() {
                    override fun onOpen(ws: WebSocket, response: Response) { execute {
                        if (current != generation) { ws.close(1000, null); return@execute }
                        val msg = Wire.message(if (code == null) "hello" else "pair").put("device", store.device)
                            .put("capabilities", org.json.JSONArray().put(FileDock.CAPABILITY).put("hub-v2"))
                        if (code != null) msg.put("code", code).put("name", android.os.Build.MODEL.take(80))
                        else msg.put("token", prefs.getString("token", ""))
                        ws.send(msg.toString())
                    } }
                    override fun onMessage(ws: WebSocket, text: String) { execute {
                        if (current != generation) return@execute
                        try {
                            val msg = Wire.decode(text)
                            when (msg.getString("type")) {
                                "paired" -> {
                                    require(code != null) { "Respuesta inesperada" }
                                    Wire.uuid(msg.getString("server"))
                                    require(msg.getString("token").length in 16..128) { "Credencial inválida" }
                                    check(prefs.edit().putString("host", host).putInt("port", port)
                                        .putString("fingerprint", fingerprint).putString("token", msg.getString("token"))
                                        .putString("server", msg.getString("server")).commit()) { "No se pudo guardar la vinculación" }
                                    active = false
                                    ws.close(1000, "Vinculado")
                                    halted("Vinculado. Pulsa Conectar.")
                                }
                                "welcome" -> {
                                    server = Wire.uuid(msg.getString("server"))
                                    require(server == prefs.getString("server", "")) { "Identidad del dock incorrecta" }
                                    fileSupport = msg.optJSONArray("capabilities")?.let { caps ->
                                        (0 until caps.length()).any { caps.optString(it) == FileDock.CAPABILITY }
                                    } ?: false
                                    hubSupport = msg.optJSONArray("capabilities")?.let { caps ->
                                        (0 until caps.length()).any { caps.optString(it) == "hub-v2" }
                                    } ?: false
                                }
                                "settings", "settings_conflict" -> {
                                    val revision = msg.getInt("revision")
                                    val values = msg.getJSONObject("values")
                                    val pending = shared.getString("pending", null)?.let(::JSONObject)
                                    val matches = pending != null && pending.keys().asSequence().all { key ->
                                        values.has(key) && if (key == "prompts") {
                                            val current = values.getJSONObject(key)
                                            val desired = pending.getJSONObject(key)
                                            listOf("image", "spelling", "grammar").all { current.optString(it) == desired.optString(it) }
                                        } else values.get(key) == pending.get(key)
                                    }
                                    shared.edit().putInt("revision", revision)
                                        .putBoolean("image", values.getBoolean("image"))
                                        .putString("text_mode", values.getString("text_mode"))
                                        .putString("prompts", values.optJSONObject("prompts")?.toString() ?: "{}")
                                        .apply()
                                    val conflict = pending != null && !matches &&
                                        shared.getInt("base_revision", 0) != revision
                                    if (matches) shared.edit().remove("pending").putBoolean("conflict", false).apply()
                                    else if (conflict) shared.edit().putBoolean("conflict", true).apply()
                                    else if (pending != null && ready) sendSharedUpdate()
                                    status(if (conflict) "Ajustes cambiados en otro dispositivo · revisa tus cambios"
                                        else "Conectado · ajustes sincronizados")
                                }
                                "ai_status" -> {
                                    val label = when (msg.getString("state")) {
                                        "pending" -> "IA · en cola"
                                        "running" -> "IA · procesando"
                                        "done" -> "IA · resultado listo"
                                        else -> "IA · error; revisa el cerebro"
                                    }
                                    status(label)
                                }
                                "devices" -> {
                                    deviceInfo = msg.getJSONArray("items").toString()
                                    status("Conectado · dispositivos actualizados")
                                }
                                "item" -> {
                                    require(server.isNotEmpty()) { "Falta saludo del servidor" }
                                    val item = msg.getJSONObject("item")
                                    val fresh = store.receive(item, server, hubSupport)
                                    ws.send(Wire.message("ack").put("id", item.getString("id")).toString())
                                    val result = msg.optJSONObject("result")
                                    if (fresh && ready && msg.optBoolean("live", false)) {
                                        app.getSystemService(ClipboardManager::class.java).setPrimaryClip(
                                            ClipData.newPlainText("Clipboard AI · IA", item.getString("text")))
                                        if (app.resources.getBoolean(R.bool.accept_external_drops)) {
                                            main.post { Toast.makeText(app, "✓ Portapapeles actualizado", Toast.LENGTH_SHORT).show() }
                                        }
                                        status(if (result != null) "✓ Resultado copiado al portapapeles"
                                               else "Conectado · texto copiado")
                                    } else status(if (ready) "Conectado · texto recibido" else "Recuperando historial…")
                                }
                                "ready" -> {
                                    require(server.isNotEmpty()) { "Falta saludo del servidor" }
                                    ready = true; connecting = false; retrySeconds = 1
                                    sendSharedUpdate()
                                    store.pending().forEach { sendItem(it, false) }
                                    ws.send(Wire.message("ready").toString())
                                    status("Conectado")
                                    offerFiles()
                                }
                                "ack" -> {
                                    store.acknowledge(msg.getString("id")); status("Conectado · entregado")
                                }
                                "error" -> {
                                    active = false; ready = false
                                    ws.close(1000, "Solicitud rechazada")
                                    halted("Rechazado: ${msg.getString("message").take(200)}")
                                }
                                else -> if (msg.getString("type").startsWith("file_") && fileSupport && server.isNotEmpty()) {
                                    fileMessage(msg)
                                } else throw IllegalArgumentException("Mensaje desconocido")
                            }
                        } catch (e: Exception) {
                            active = false; ready = false; ws.close(1000, "Protocolo inválido")
                            halted(e.message ?: "Mensaje inválido")
                        }
                    } }
                    override fun onMessage(ws: WebSocket, bytes: ByteString) {
                        ws.close(1003, "Solo texto JSON")
                    }
                    override fun onClosing(ws: WebSocket, code: Int, reason: String) { ws.close(code, reason) }
                    override fun onClosed(ws: WebSocket, code: Int, reason: String) { execute {
                        if (current != generation) return@execute
                        ready = false; connecting = false
                        if (active && (code == 4001 || code == 4003)) { halted("Vinculación rechazada o revocada. Vuelve a vincular este dispositivo.") }
                        else if (active) reconnect(current, host, port, fingerprint)
                    } }
                    override fun onFailure(ws: WebSocket, error: Throwable, response: Response?) { execute {
                        if (current != generation) return@execute
                        ready = false; connecting = false
                        val explanation = ConnectionFailure.message(error)
                        if (explanation.startsWith("La identidad TLS")) halted(explanation)
                        else if (pairing) halted("No se pudo vincular. $explanation")
                        else if (active) reconnect(current, host, port, fingerprint, explanation)
                    } }
                })
        } catch (e: Exception) { connecting = false; halted(e.message ?: "No se pudo conectar") }
    }
    /** Promptly retry when the default network returns, without waiting for a suspended timer. */
    fun networkAvailable() = execute {
        if (active && !ready && !connecting && !pairing && hasCredentials())
            open(endpoint(), endpointPort(), prefs.getString("fingerprint", "")!!, null)
    }

    private fun reconnect(current: Int, host: String, port: Int, fingerprint: String, reason: String? = null) {
        status("${reason ?: "Sin conexión"} · reintento en ${retrySeconds} s")
        worker.schedule({ if (active && current == generation) open(host, port, fingerprint, null) },
            retrySeconds, TimeUnit.SECONDS)
        retrySeconds = (retrySeconds * 2).coerceAtMost(30)
    }
    private fun sendItem(item: JSONObject, live: Boolean) {
        socket?.send(Wire.message("item").put("item", item).put("live", live).toString())
    }
    fun sharedSettings(done: (Boolean, String, Boolean) -> Unit) = execute {
        val pending = shared.getString("pending", null)?.let(::JSONObject)
        val image = pending?.optBoolean("image") ?: shared.getBoolean("image", false)
        val mode = pending?.optString("text_mode") ?: shared.getString("text_mode", "none").orEmpty()
        main.post { done(image, mode, pending != null) }
    }
    fun devices(done: (List<String>) -> Unit) = execute {
        val items = org.json.JSONArray(deviceInfo)
        val labels = (0 until items.length()).map { index ->
            val item = items.getJSONObject(index)
            item.getString("name") + if (item.getBoolean("connected")) " · conectado" else " · sin conexión"
        }
        main.post { done(labels) }
    }
    fun sharedPrompts(done: (JSONObject) -> Unit) = execute {
        val pending = shared.getString("pending", null)?.let(::JSONObject)?.optJSONObject("prompts")
        val prompts = pending ?: JSONObject(shared.getString("prompts", "{}").orEmpty())
        main.post { done(prompts) }
    }
    fun updateShared(image: Boolean? = null, textMode: String? = null, prompts: JSONObject? = null) = execute {
        require(textMode == null || textMode in listOf("none", "spelling", "grammar"))
        val conflict = shared.getBoolean("conflict", false)
        val patch = if (conflict) JSONObject() else shared.getString("pending", null)?.let(::JSONObject) ?: JSONObject()
        if (conflict || shared.getString("pending", null) == null)
            shared.edit().putInt("base_revision", shared.getInt("revision", 0))
                .putBoolean("conflict", false).apply()
        if (image != null) patch.put("image", image)
        if (textMode != null) patch.put("text_mode", textMode)
        if (prompts != null) patch.put("prompts", prompts)
        shared.edit().putString("pending", patch.toString()).apply()
        sendSharedUpdate()
        status(if (ready) "Ajuste enviado · esperando confirmación" else "Ajuste pendiente de conexión")
    }
    fun retrySharedSettings() = execute {
        if (shared.getString("pending", null) == null) {
            status("No hay ajustes pendientes")
            return@execute
        }
        shared.edit().putInt("base_revision", shared.getInt("revision", 0))
            .putBoolean("conflict", false).apply()
        sendSharedUpdate()
        status("Reenviando ajustes pendientes")
    }
    private fun sendSharedUpdate() {
        if (!ready || !hubSupport || shared.getBoolean("conflict", false)) return
        val patch = shared.getString("pending", null)?.let(::JSONObject) ?: return
        socket?.send(Wire.message("settings_update")
            .put("base_revision", shared.getInt("base_revision", 0)).put("changes", patch).toString())
    }
    private fun offerFiles() {
        if (!ready || !fileSupport) return
        (files.notices() + files.offers()).forEach { socket?.send(it.toString()) }
    }
    private fun fileMessage(msg: JSONObject) {
        try {
            val reply = files.handle(msg, server, hubSupport)
            if (reply != null) {
                if (reply.getString("type") == "file_chunk") {
                    val key = reply.getString("id") to reply.getLong("offset")
                    if (lastFileChunk == key) return
                    lastFileChunk = key
                }
                socket?.send(reply.toString())
            }
            val terminal = msg.getString("type") in listOf("file_done", "file_cancelled", "file_error") || reply?.optString("type") == "file_done"
            val now = android.os.SystemClock.elapsedRealtime()
            if (terminal || now - lastFileUpdate >= 500) {
                lastFileUpdate = now; status("Conectado · dock de archivos actualizado")
            }
            if (terminal) offerFiles()
        } catch (e: Exception) {
            val id = msg.optString("id").ifEmpty { msg.optJSONObject("file")?.optString("id").orEmpty() }
            if (runCatching { Wire.uuid(id) }.isSuccess) {
                files.failReceiving(id, e.message ?: "Error de archivo")
                socket?.send(Wire.message("file_error").put("id", id).put("message", (e.message ?: "Error de archivo").take(200)).toString())
            }
            status("Archivo: ${e.message ?: "no se pudo transferir"}")
        }
    }
    fun importFile(uri: Uri, done: (Boolean) -> Unit) {
        status("Preparando archivo…")
        importer.execute {
            try {
                var name = uri.lastPathSegment?.substringAfterLast('/')?.takeIf { it.isNotBlank() } ?: "archivo"
                var declaredSize: Long? = null
                app.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { c ->
                    if (c.moveToFirst()) {
                        val n = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                        if (n >= 0 && !c.isNull(n)) name = c.getString(n)
                        val s = c.getColumnIndex(OpenableColumns.SIZE)
                        if (s >= 0 && !c.isNull(s) && c.getLong(s) >= 0) declaredSize = c.getLong(s)
                    }
                }
                declaredSize?.let { require(it in 0..FileDock.MAX_FILE) { "El archivo supera 100 MiB" }; files.capacity(it) }
                val input = requireNotNull(app.contentResolver.openInputStream(uri)) { "No se pudo leer el archivo" }
                val declaredType = app.contentResolver.getType(uri)
                val extension = name.substringAfterLast('.', "").lowercase()
                val guessedType = android.webkit.MimeTypeMap.getSingleton().getMimeTypeFromExtension(extension)
                    ?: when (extension) {
                        "png" -> "image/png"
                        "jpg", "jpeg" -> "image/jpeg"
                        "webp" -> "image/webp"
                        "heic", "heif" -> "image/heic"
                        "gif" -> "image/gif"
                        else -> null
                    }
                val mime = if (declaredType.isNullOrBlank() || declaredType == "application/octet-stream")
                    guessedType ?: "application/octet-stream" else declaredType
                val item = input.use { files.prepare(it, name, mime) }
                execute {
                    try {
                        files.commitPrepared(item); offerFiles()
                        status(if (ready && !fileSupport) "Archivo guardado. Actualiza Windows a 0.2 para enviarlo." else "Archivo preparado · envío pendiente")
                        main.post { done(true) }
                    } catch (e: Exception) { status(e.message ?: "No se pudo guardar el archivo"); main.post { done(false) } }
                }
            } catch (e: Exception) { status(e.message ?: "No se pudo importar el archivo"); main.post { done(false) } }
        }
    }
    fun fileHistory(done: (List<DockFile>) -> Unit) = execute {
        val items = files.history(); main.post { done(items) }
    }
    fun deliveredUsage(done: (Int, Long) -> Unit) = execute {
        val (count, bytes) = files.deliveredUsage(); main.post { done(count, bytes) }
    }
    fun clearDelivered() = execute {
        try { files.clearDelivered(); status("Copias entregadas borradas del dock local") }
        catch (e: Exception) { status(e.message ?: "No se pudo limpiar el dock") }
    }
    fun fileAction(id: String, action: String) = execute {
        try {
            if (action == "cancel") files.cancel(id) else files.delete(id)
            offerFiles(); status("Dock de archivos actualizado")
        } catch (e: Exception) { status(e.message ?: "No se pudo completar") }
    }
    fun exportFile(id: String, uri: Uri, done: (Boolean) -> Unit) = execute {
        try {
            val row = files.get(id)
            require(row.state == "delivered" || row.direction == "out" && row.state in listOf("pending", "sending")) {
                "El archivo todavía no está completo"
            }
            importer.execute {
                try {
                    File(row.path).inputStream().use { src ->
                        requireNotNull(app.contentResolver.openOutputStream(uri, "wt")).use { dst -> src.copyTo(dst, FileDock.CHUNK) }
                    }
                    status("Copia guardada"); main.post { done(true) }
                } catch (e: Exception) { status(e.message ?: "No se pudo exportar"); main.post { done(false) } }
            }
        } catch (e: Exception) { status(e.message ?: "No se pudo exportar"); main.post { done(false) } }
    }
    fun publish(text: String, done: (Boolean) -> Unit) = execute {
        try {
            val item = store.create(text)
            if (ready) sendItem(item, true)
            status(if (ready) "Enviado · esperando confirmación" else "Guardado · pendiente de conexión")
            main.post { done(true) }
        } catch (e: Exception) { status(e.message ?: "No se pudo guardar"); main.post { done(false) } }
    }
    fun history(done: (List<DockItem>) -> Unit) = execute {
        val items = store.history(); main.post { done(items) }
    }
    fun textUsage(done: (Int, Int) -> Unit) = execute {
        val (total, pending) = store.textUsage(); main.post { done(total, pending) }
    }
    fun clearTexts(done: (Int) -> Unit) = execute {
        val count = store.clearTexts()
        status("$count textos borrados del dock local")
        main.post { done(count) }
    }
    fun delete(id: String) = execute { store.delete(id); status("Borrado del dock local") }
    private fun stopSocket() {
        generation++; ready = false; connecting = false; server = ""
        fileSupport = false; hubSupport = false; lastFileChunk = null
        socket?.cancel(); socket = null
        client?.connectionPool?.evictAll()
        client?.dispatcher?.executorService?.shutdown()
        client = null
    }
    fun disconnect() = execute { active = false; stopSocket(); status("Desconectado") }
    fun close() {
        execute { active = false; stopSocket() }
        // Imports already accepted retain their URI grants through completion and commit before closing SQLite.
        importer.shutdown()
        Thread {
            try { importer.awaitTermination(5, TimeUnit.MINUTES) } catch (_: InterruptedException) { Thread.currentThread().interrupt() }
            execute { store.close(); files.close() }
            worker.shutdown()
        }.apply { isDaemon = true; start() }
    }
}
