package org.clipboardai.app

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Binder
import android.os.Build
import android.os.PowerManager
import android.net.ConnectivityManager
import android.net.Network

/** Owns the socket independently of activities, including while the screen is locked. */
class DockService : Service() {
    inner class LocalBinder : Binder() { val service get() = this@DockService }
    private val binder = LocalBinder()
    private val listeners = mutableSetOf<(String) -> Unit>()
    private val preferences by lazy { getSharedPreferences("background", MODE_PRIVATE) }
    private lateinit var wakeLock: PowerManager.WakeLock
    lateinit var connection: DockConnection
        private set
    private lateinit var screenshots: ScreenshotWatcher
    var keepingConnection = false
        private set
    private var destroyed = false
    private var lastStatus = "Desconectado"
    private var watchingNetwork = false
    private val networkCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) { connection.networkAvailable() }
    }
    private fun watchNetwork() {
        if (!watchingNetwork) {
            getSystemService(ConnectivityManager::class.java).registerDefaultNetworkCallback(networkCallback)
            watchingNetwork = true
        }
    }
    private fun unwatchNetwork() {
        if (watchingNetwork) {
            getSystemService(ConnectivityManager::class.java).unregisterNetworkCallback(networkCallback)
            watchingNetwork = false
        }
    }

    override fun onCreate() {
        super.onCreate()
        val previousStarts = preferences.getInt("starts", 0)
        val unexpectedRestart = previousStarts > 0 && preferences.getBoolean("enabled", false)
        preferences.edit().putLong("last_created", System.currentTimeMillis())
            .putInt("starts", previousStarts + 1)
            .apply { if (unexpectedRestart) putLong("last_unexpected_restart", System.currentTimeMillis()) }
            .apply()
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL, "Conexión con el ordenador", NotificationManager.IMPORTANCE_LOW))
        wakeLock = getSystemService(PowerManager::class.java)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "ClipboardAI:connection")
        connection = DockConnection(applicationContext, DockStore(applicationContext),
            onStopped = { if (!destroyed) endForeground() }) { text ->
            if (!destroyed) {
                lastStatus = text
                if (keepingConnection) getSystemService(NotificationManager::class.java)
                    .notify(NOTIFICATION, notification())
                listeners.toList().forEach { it(text) }
            }
        }
        screenshots = ScreenshotWatcher(applicationContext) { uri, done -> connection.importFile(uri, done) }
    }

    override fun onBind(intent: Intent) = binder
    fun observe(listener: (String) -> Unit) { listeners.add(listener); listener(lastStatus) }
    fun removeObserver(listener: (String) -> Unit) { listeners.remove(listener) }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == PAUSE) { pause(); return START_NOT_STICKY }
        if (intent?.action != CONNECT && !(intent == null && preferences.getBoolean("enabled", false))) {
            stopSelf(); return START_NOT_STICKY
        }
        // Promote immediately, even when credentials are missing, to satisfy startForegroundService.
        if (!keepingConnection) {
            lastStatus = "Conectando…"
            if (Build.VERSION.SDK_INT >= 29)
                startForeground(NOTIFICATION, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
            else startForeground(NOTIFICATION, notification())
            keepingConnection = true
            preferences.edit().putBoolean("enabled", true).apply()
            if (connection.hasCredentials()) holdCpuForConnection()
            connection.connect()
            watchNetwork()
            screenshots.start()
        }
        return START_STICKY
    }

    // This user-controlled continuous LAN session needs to answer WebSocket pings while locked.
    // Released on Pause, terminal connection error and onDestroy; never keeps the screen on.
    @SuppressLint("WakelockTimeout")
    private fun holdCpuForConnection() { if (!wakeLock.isHeld) wakeLock.acquire() }

    fun pair(data: PairingData) { pause(); connection.pair(data) }
    fun pause() { screenshots.stop(); endForeground(); connection.disconnect() }
    fun setScreenshotCapture(enabled: Boolean) {
        screenshots.setEnabled(enabled)
        if (!keepingConnection) screenshots.stop()
    }
    private fun endForeground() {
        unwatchNetwork()
        screenshots.stop()
        preferences.edit().putBoolean("enabled", false).apply()
        keepingConnection = false
        if (wakeLock.isHeld) wakeLock.release()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun notification(): Notification {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val pause = PendingIntent.getService(this, 1, Intent(this, DockService::class.java).setAction(PAUSE),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, CHANNEL).setSmallIcon(R.drawable.ic_app)
            .setContentTitle("Clipboard AI · conexión activa").setContentText(lastStatus)
            .setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true)
            .setCategory(Notification.CATEGORY_SERVICE).setVisibility(Notification.VISIBILITY_PRIVATE)
            .addAction(Notification.Action.Builder(null, "Pausar", pause).build()).build()
    }

    override fun onDestroy() {
        unwatchNetwork()
        preferences.edit().putLong("last_destroyed", System.currentTimeMillis()).apply()
        destroyed = true
        listeners.clear()
        if (wakeLock.isHeld) wakeLock.release()
        screenshots.close()
        connection.close()
        super.onDestroy()
    }

    companion object {
        const val CONNECT = "org.clipboardai.app.CONNECT"
        const val PAUSE = "org.clipboardai.app.PAUSE"
        private const val CHANNEL = "connection"
        private const val NOTIFICATION = 1
    }
}
