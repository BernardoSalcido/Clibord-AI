package org.clipboardai.app

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.ComponentName
import android.content.Intent
import android.content.ServiceConnection
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Button

internal sealed interface ClipboardContent {
    data class Text(val value: String) : ClipboardContent
    data class File(val uri: Uri) : ClipboardContent
}

/** Do not coerce a copied image URI into its filename or URI string. */
internal fun clipboardContent(clip: ClipData?): ClipboardContent? {
    if (clip == null || clip.itemCount == 0) return null
    val item = clip.getItemAt(0)
    val uri = item.uri
    if (uri != null && (item.text == null || clip.description.hasMimeType("image/*")))
        return ClipboardContent.File(uri)
    val text = item.text?.toString()?.takeIf { it.isNotBlank() }
    return if (text != null) ClipboardContent.Text(text) else uri?.let { ClipboardContent.File(it) }
}

internal fun clipboardUris(clip: ClipData?): List<Uri> = buildList {
    if (clip != null) for (index in 0 until clip.itemCount) clip.getItemAt(index).uri?.let { add(it) }
}.distinct()

/** Brief foreground window, required for clipboard reads on Android 10+. */
class SendClipboardActivity : Activity() {
    private lateinit var message: TextView
    private var service: DockService? = null
    private var bound = false
    private var focused = false
    private var started = false
    private val handler = Handler(Looper.getMainLooper())

    private val binding = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName, binder: IBinder) {
            service = (binder as DockService.LocalBinder).service
            sendWhenReady()
        }
        override fun onServiceDisconnected(name: ComponentName) {
            service = null
            if (!started) message.text = "No se pudo abrir el dock local"
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val padding = (20 * resources.displayMetrics.density).toInt()
            setPadding(padding, padding, padding, padding)
        }
        message = TextView(this).apply { text = "Preparando portapapeles…"; textSize = 17f }
        layout.addView(message, LinearLayout.LayoutParams(-1, -2))
        layout.addView(Button(this).apply { text = "Cerrar"; setOnClickListener { finish() } },
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        setContentView(layout)
    }

    override fun onStart() {
        super.onStart()
        bound = bindService(Intent(this, DockService::class.java), binding, BIND_AUTO_CREATE)
        if (!bound) message.text = "No se pudo abrir el dock local"
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        focused = hasFocus
        if (hasFocus) sendWhenReady()
    }

    private fun sendWhenReady() {
        val dock = service ?: return
        if (!focused || started) return
        started = true
        val clip = getSystemService(ClipboardManager::class.java).primaryClip
        val uris = clipboardUris(clip).take(20)
        if (uris.isNotEmpty()) {
            var finished = 0
            var saved = 0
            message.text = "Guardando ${uris.size} archivo(s)…"
            uris.forEach { uri ->
                dock.connection.importFile(uri) { success ->
                    finished++
                    if (success) saved++
                    if (!isDestroyed) message.text = "Guardados $saved de $finished · ${uris.size} seleccionados"
                    if (finished == uris.size) complete(saved == uris.size,
                        "$saved archivo(s) añadidos al dock", "$saved de ${uris.size} guardados; abre Clipboard AI para revisar los errores")
                }
            }
            return
        }
        when (val content = clipboardContent(clip)) {
            is ClipboardContent.Text -> {
                message.text = "Guardando texto…"
                dock.connection.publish(content.value) { success ->
                    complete(success, "Texto añadido al dock", "No se pudo guardar el texto; abre Clipboard AI")
                }
            }
            is ClipboardContent.File -> { /* Covered by clipboardUris. */ }
            null -> message.text = "No hay texto, imagen o archivo disponible en el portapapeles"
        }
    }

    private fun complete(success: Boolean, ok: String, error: String) {
        if (isDestroyed) return
        message.text = if (success) ok else error
        if (success) handler.postDelayed({ if (!isDestroyed) finish() }, 1100)
    }

    override fun onStop() {
        if (bound) { unbindService(binding); bound = false; service = null }
        super.onStop()
    }
}
