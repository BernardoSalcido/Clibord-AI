package org.clipboardai.app

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.database.ContentObserver
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import java.util.concurrent.Executors

/** Imports new screenshots once MediaStore has finished writing them. */
class ScreenshotWatcher(private val context: Context, private val import: (Uri, (Boolean) -> Unit) -> Unit) {
    private val preferences = context.getSharedPreferences("screenshots", Context.MODE_PRIVATE)
    private val worker = Executors.newSingleThreadExecutor()
    private val retryHandler = Handler(Looper.getMainLooper())
    @Volatile private var registered = false
    private var busy = false
    private val uri = MediaStore.Images.Media.EXTERNAL_CONTENT_URI
    private val observer = object : ContentObserver(Handler(Looper.getMainLooper())) {
        override fun onChange(selfChange: Boolean) { scan() }
        override fun onChange(selfChange: Boolean, uri: Uri?) { scan() }
    }

    fun enabled() = preferences.getBoolean("enabled", false)
    fun setEnabled(value: Boolean) {
        preferences.edit().putBoolean("enabled", value).apply()
        if (value) start() else stop()
    }
    private fun permitted(): Boolean = Build.VERSION.SDK_INT >= 29 &&
        context.checkSelfPermission(if (Build.VERSION.SDK_INT >= 33) Manifest.permission.READ_MEDIA_IMAGES
            else Manifest.permission.READ_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED

    fun start() {
        if (registered || !enabled() || !permitted()) return
        registered = true
        context.contentResolver.registerContentObserver(uri, true, observer)
        scan()
    }
    fun stop() {
        if (registered) context.contentResolver.unregisterContentObserver(observer)
        registered = false
        retryHandler.removeCallbacksAndMessages(null)
    }
    private fun retry() {
        retryHandler.postDelayed({ if (registered) scan() }, 1500)
    }
    private fun scan() {
        if (!registered) return
        worker.execute {
            if (busy || !registered) return@execute
            val projection = arrayOf(MediaStore.Images.Media._ID, MediaStore.Images.Media.DISPLAY_NAME,
                MediaStore.Images.Media.RELATIVE_PATH, MediaStore.Images.Media.IS_PENDING)
            try {
                if (!preferences.contains("cursor")) {
                    val initial = context.contentResolver.query(uri, arrayOf(MediaStore.Images.Media._ID), null, null,
                        "${MediaStore.Images.Media._ID} DESC")?.use { result ->
                        if (result.moveToFirst()) result.getLong(0) else 0L
                    }
                    preferences.edit().putLong("cursor", initial ?: 0L).apply()
                    return@execute
                }
                val cursor = preferences.getLong("cursor", 0)
                context.contentResolver.query(uri, projection, "${MediaStore.Images.Media._ID} > ?",
                    arrayOf(cursor.toString()), "${MediaStore.Images.Media._ID} ASC")?.use { result ->
                    while (registered && result.moveToNext()) {
                        val id = result.getLong(0)
                        val name = result.getString(1).orEmpty().lowercase()
                        val path = result.getString(2).orEmpty().lowercase()
                        val screenshot = listOf("screenshot", "screen_shot", "captura", "screenshots")
                            .any { it in name || it in path }
                        if (!screenshot) {
                            preferences.edit().putLong("cursor", id).apply()
                            continue
                        }
                        if (result.getInt(3) != 0) {
                            retry()
                            return@use
                        }
                        busy = true
                        import(Uri.withAppendedPath(uri, id.toString())) { saved ->
                            runCatching { worker.execute {
                                if (saved) preferences.edit().putLong("cursor", id).apply()
                                busy = false
                                if (saved) scan() else retry()
                            } }
                        }
                        return@use
                    }
                }
            } catch (_: SecurityException) { /* Permission was revoked while the service ran. */ }
        }
    }
    fun close() { stop(); worker.shutdown() }
}
