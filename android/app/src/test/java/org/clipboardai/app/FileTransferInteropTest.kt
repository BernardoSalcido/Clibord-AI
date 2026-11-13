package org.clipboardai.app

import android.content.ComponentName
import android.content.Intent
import android.os.Looper
import android.net.Uri
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import java.io.File
import java.io.ByteArrayOutputStream
import java.net.URI

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class FileTransferInteropTest {
    private fun awaitCondition(condition: () -> Boolean) {
        val deadline = System.nanoTime() + 50_000_000_000L
        while (System.nanoTime() < deadline) {
            shadowOf(Looper.getMainLooper()).idle()
            if (condition()) return
            Thread.sleep(20)
        }
        fail("No se completó la transferencia de archivos")
    }
    @Test fun realServiceTransfersBothDirectionsResumesAfterDisconnectAndKeepsTextWorking() {
        val path = System.getenv("CLIPBOARD_AI_FILES_TEST")
        assumeTrue("Servidor de archivos opcional no iniciado", !path.isNullOrEmpty())
        val config = JSONObject(File(path!!).readText())
        val url = URI(config.getString("url")); val app = RuntimeEnvironment.getApplication()
        val controller = Robolectric.buildService(DockService::class.java).create()
        val service = controller.get()
        var status = ""; service.observe { status = it }
        shadowOf(app).setComponentNameAndServiceForBindService(ComponentName(app, DockService::class.java), service.onBind(Intent()))
        val activity = Robolectric.buildActivity(MainActivity::class.java).setup()
        var activityAlive = true
        try {
            service.pair(PairingData.fields(url.host, url.port.toString(), config.getString("fingerprint"), config.getString("code")))
            awaitCondition { status.startsWith("Vinculado.") }
            val upload = File(service.connection.files.root, "Desde Android á.bin").apply {
                writeBytes(ByteArray(380_123) { (it % 251).toByte() })
            }
            val uri = Uri.parse("content://clipboard-ai-test/upload")
            shadowOf(app.contentResolver).registerInputStream(uri, upload.inputStream())
            var imported = false
            service.connection.importFile(uri) { imported = it }
            awaitCondition { imported }
            service.onStartCommand(Intent().setAction(DockService.CONNECT), 0, 1)
            activity.pause().stop().destroy(); activityAlive = false
            var items: List<DockFile> = emptyList()
            awaitCondition {
                service.connection.fileHistory { items = it }
                items.count { it.state == "delivered" } == 2
            }
            val downloaded = items.first { it.direction == "in" }
            assertEquals(config.getString("downloadHash"), FileDock.digest(File(downloaded.path)))
            val exported = ByteArrayOutputStream()
            val destination = Uri.parse("content://clipboard-ai-test/export")
            shadowOf(app.contentResolver).registerOutputStream(destination, exported)
            var saved = false
            service.connection.exportFile(downloaded.id, destination) { saved = it }
            awaitCondition { saved }
            assertArrayEquals(File(downloaded.path).readBytes(), exported.toByteArray())
            assertArrayEquals(upload.readBytes(), File(items.first { it.direction == "out" }.path).readBytes())
            var sent = false
            service.connection.publish(config.getString("text")) { sent = it }
            awaitCondition { sent && status.contains("entregado") }
            service.onStartCommand(Intent().setAction(DockService.PAUSE), 0, 2)
        } finally {
            if (activityAlive) activity.pause().stop().destroy()
            controller.destroy()
        }
    }
}
