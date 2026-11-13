package org.clipboardai.app

import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File
import java.util.UUID
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/** Runs against the real Python TLS server via scripts/verify_interop.py. */
class DesktopInteropTest {
    @Test fun rejectsWrongPinnedCertificate() {
        val path = System.getenv("CLIPBOARD_AI_INTEROP")
        assumeTrue("Servidor de integración opcional no iniciado", !path.isNullOrEmpty())
        val config = JSONObject(File(path!!).readText())
        val client = PinnedTls.client("0".repeat(64))
        val result = LinkedBlockingQueue<Any>()
        val socket = client.newWebSocket(Request.Builder().url(config.getString("url")).build(),
            object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) { result.offer("accepted") }
                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { result.offer(t) }
            })
        try { assertTrue("Una huella incorrecta debe rechazar el servidor", result.poll(15, TimeUnit.SECONDS) is Throwable) }
        finally {
            socket.cancel(); client.connectionPool.evictAll(); client.dispatcher.executorService.shutdown()
        }
    }
    @Test fun kotlinAndPythonExchangeTextOverPinnedTls() {
        val path = System.getenv("CLIPBOARD_AI_INTEROP")
        assumeTrue("Servidor de integración opcional no iniciado", !path.isNullOrEmpty())
        val config = JSONObject(File(path!!).readText())
        val client = PinnedTls.client(config.getString("fingerprint"))
        val queue = LinkedBlockingQueue<Any>()
        fun listener() = object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, text: String) { queue.offer(Wire.decode(text)) }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { queue.offer(t) }
        }
        fun receive(): JSONObject {
            val value = queue.poll(15, TimeUnit.SECONDS)
            if (value is Throwable) throw AssertionError("TLS/WebSocket falló", value)
            require(value is JSONObject) { "No llegó respuesta del servidor" }
            assertNotEquals("error", value.getString("type"))
            return value
        }
        val request = Request.Builder().url(config.getString("url")).build()
        val peer = UUID.randomUUID().toString()
        var socket: WebSocket? = null
        try {
            socket = client.newWebSocket(request, listener())
            socket.send(Wire.message("pair").put("device", peer).put("name", "Prueba Kotlin")
                .put("code", config.getString("code")).toString())
            val paired = receive()
            assertEquals("paired", paired.getString("type"))
            socket.close(1000, "Vinculado")
            socket = client.newWebSocket(request, listener())
            socket.send(Wire.message("hello").put("device", peer).put("token", paired.getString("token")).toString())
            assertEquals("welcome", receive().getString("type"))
            val desktop = receive()
            assertEquals("item", desktop.getString("type"))
            assertEquals(config.getString("text"), Wire.item(desktop.getJSONObject("item")).getString("text"))
            socket.send(Wire.message("ack").put("id", desktop.getJSONObject("item").getString("id")).toString())
            assertEquals("ready", receive().getString("type"))
            socket.send(Wire.message("ready").toString())
            val item = JSONObject().put("id", UUID.randomUUID().toString()).put("origin", peer)
                .put("seq", 1).put("created", "2026-10-15T12:00:00Z").put("text", config.getString("text"))
            val message = Wire.message("item").put("live", true).put("item", Wire.item(item)).toString()
            socket.send(message)
            assertEquals(item.getString("id"), receive().getString("id"))
            socket.send(message)
            assertEquals(item.getString("id"), receive().getString("id"))
        } finally {
            socket?.cancel()
            client.connectionPool.evictAll()
            client.dispatcher.executorService.shutdown()
        }
    }
}
