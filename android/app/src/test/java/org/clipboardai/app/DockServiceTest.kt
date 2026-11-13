package org.clipboardai.app

import android.app.Service
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Looper
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowPowerManager

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class DockServiceTest {
    private fun credentials() {
        RuntimeEnvironment.getApplication().getSharedPreferences("connection", Context.MODE_PRIVATE)
            .edit().putString("token", "test-token-not-a-real-credential")
            .putString("host", "127.0.0.1").putInt("port", 9)
            .putString("fingerprint", "0".repeat(64)).commit()
    }

    @Test fun connectionSurvivesActivityStopAndRecreationAndPauseReleasesResources() {
        credentials()
        val controller = Robolectric.buildService(DockService::class.java).create()
        val service = controller.get()
        val app = RuntimeEnvironment.getApplication()
        shadowOf(app).setComponentNameAndServiceForBindService(
            ComponentName(app, DockService::class.java), service.onBind(Intent()))
        val first = Robolectric.buildActivity(MainActivity::class.java).setup()
        shadowOf(Looper.getMainLooper()).idle()
        val connection = service.connection
        try {
            assertEquals(Service.START_STICKY,
                service.onStartCommand(Intent().setAction(DockService.CONNECT), 0, 1))
            val lock = ShadowPowerManager.getLatestWakeLock()
            assertTrue(lock.isHeld)
            assertEquals(ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE, service.foregroundServiceType)
            assertTrue(shadowOf(service).isLastForegroundNotificationAttached)
            first.pause().stop().destroy()
            assertTrue(service.keepingConnection)
            assertTrue(lock.isHeld)
            val second = Robolectric.buildActivity(MainActivity::class.java).setup()
            shadowOf(Looper.getMainLooper()).idle()
            service.onStartCommand(Intent().setAction(DockService.CONNECT), 0, 2)
            assertSame(connection, service.connection)
            second.pause().stop().destroy()
            val notification = shadowOf(service).lastForegroundNotification
            // Execute the same command represented by the notification's pause action.
            assertEquals(DockService.PAUSE, shadowOf(notification.actions[0].actionIntent).savedIntent.action)
            service.onStartCommand(Intent().setAction(DockService.PAUSE), 0, 3)
            assertFalse(service.keepingConnection)
            assertFalse(lock.isHeld)
            assertTrue(shadowOf(service).isForegroundStopped)
            assertFalse(service.getSharedPreferences("background", Context.MODE_PRIVATE).getBoolean("enabled", true))
        } finally { controller.destroy() }
    }

    @Test fun missingCredentialsStopsForegroundInsteadOfLeavingIdleNotification() {
        val controller = Robolectric.buildService(DockService::class.java).create()
        val service = controller.get()
        try {
            service.onStartCommand(Intent().setAction(DockService.CONNECT), 0, 1)
            val deadline = System.nanoTime() + 5_000_000_000L
            while (service.keepingConnection && System.nanoTime() < deadline) {
                Thread.sleep(10); shadowOf(Looper.getMainLooper()).idle()
            }
            assertFalse(service.keepingConnection)
            assertFalse(ShadowPowerManager.getLatestWakeLock().isHeld)
            assertTrue(shadowOf(service).isStoppedBySelf)
        } finally { controller.destroy() }
    }

    @Test fun systemRestartResumesEnabledSessionButDoesNotResumePausedSession() {
        credentials()
        val first = Robolectric.buildService(DockService::class.java).create()
        first.get().onStartCommand(Intent().setAction(DockService.CONNECT), 0, 1)
        first.destroy()
        assertFalse(ShadowPowerManager.getLatestWakeLock().isHeld)
        val restarted = Robolectric.buildService(DockService::class.java).create()
        try {
            assertEquals(Service.START_STICKY, restarted.get().onStartCommand(null, 0, 2))
            assertTrue(restarted.get().keepingConnection)
            restarted.get().pause()
        } finally { restarted.destroy() }
        val paused = Robolectric.buildService(DockService::class.java).create()
        try {
            assertEquals(Service.START_NOT_STICKY, paused.get().onStartCommand(null, 0, 3))
            assertFalse(paused.get().keepingConnection)
            assertFalse(ShadowPowerManager.getLatestWakeLock().isHeld)
        } finally { paused.destroy() }
    }
}
