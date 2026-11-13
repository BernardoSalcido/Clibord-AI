package org.clipboardai.app

import android.content.ComponentName
import android.content.Intent
import android.os.Looper
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
import java.net.URI

/** Actual service, database and WebSocket against Python, with a simulated Android 14 lifecycle. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class BackgroundConnectionTest {
    private fun awaitCondition(condition: () -> Boolean) {
        val deadline = System.nanoTime() + 20_000_000_000L
        while (System.nanoTime() < deadline) {
            shadowOf(Looper.getMainLooper()).idle()
            if (condition()) return
            Thread.sleep(20)
        }
        fail("No se completó el intercambio en segundo plano")
    }

    @Test fun receivesAndAcknowledgesWhileActivityIsStoppedAndReopensSameSession() {
        val path = System.getenv("CLIPBOARD_AI_BACKGROUND_TEST")
        assumeTrue("Servidor de prueba opcional no iniciado", !path.isNullOrEmpty())
        val config = JSONObject(File(path!!).readText())
        val url = URI(config.getString("url"))
        val app = RuntimeEnvironment.getApplication()
        val controller = Robolectric.buildService(DockService::class.java).create()
        val service = controller.get()
        shadowOf(app).setComponentNameAndServiceForBindService(
            ComponentName(app, DockService::class.java), service.onBind(Intent()))
        var status = ""
        service.observe { status = it }
        var activity = Robolectric.buildActivity(MainActivity::class.java).setup()
        var activityAlive = true
        try {
            service.pair(PairingData.fields(url.host, url.port.toString(), config.getString("fingerprint"), config.getString("code")))
            awaitCondition { status.startsWith("Vinculado.") }
            service.onStartCommand(Intent().setAction(DockService.CONNECT), 0, 1)
            awaitCondition { status == "Conectado" }
            val socketOwner = service.connection
            activity.pause().stop().destroy(); activityAlive = false
            // Only after the Activity is gone does the helper publish a new desktop item.
            var sent = false
            service.connection.publish("request-after-screen-off") { sent = it }
            awaitCondition { sent }
            var items: List<DockItem> = emptyList()
            val expected = config.getString("text") + "\nCon la pantalla apagada"
            awaitCondition {
                service.connection.history { items = it }
                items.any { it.value.getString("text") == expected }
            }
            assertTrue(service.keepingConnection)
            assertTrue(items.any { it.value.getString("text") == config.getString("text") })
            activity = Robolectric.buildActivity(MainActivity::class.java).setup(); activityAlive = true
            shadowOf(Looper.getMainLooper()).idle()
            assertSame(socketOwner, service.connection)
            service.onStartCommand(Intent().setAction(DockService.PAUSE), 0, 2)
            assertFalse(service.keepingConnection)
        } finally {
            if (activityAlive) activity.pause().stop().destroy()
            controller.destroy()
        }
    }
}
