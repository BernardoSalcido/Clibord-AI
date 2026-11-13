package org.clipboardai.app

import android.app.Activity
import android.content.ComponentName
import android.content.Intent
import android.content.ServiceConnection
import android.os.Bundle
import android.os.IBinder
import android.widget.Toast

/** Keeps the temporary URI grant until every shared file has been copied into the dock. */
class ShareReceiverActivity : Activity() {
    private var bound = false
    private var started = false
    private val binding = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName, binder: IBinder) {
            if (!bound || started) return
            started = true
            receive((binder as DockService.LocalBinder).service)
        }
        override fun onServiceDisconnected(name: ComponentName) { finish() }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.setDimAmount(0f)
    }

    override fun onStart() {
        super.onStart()
        bound = bindService(Intent(this, DockService::class.java), binding, BIND_AUTO_CREATE)
        if (!bound) finish()
    }

    private fun receive(service: DockService) {
        val uris = incomingUris(intent).take(20)
        if (uris.isNotEmpty()) {
            var remaining = uris.size
            var saved = 0
            uris.forEach { uri -> service.connection.importFile(uri) { success ->
                if (success) saved++
                remaining--
                if (remaining == 0 && !isFinishing) {
                    Toast.makeText(this, if (saved == uris.size) "${saved} archivo(s) en el dock"
                        else "$saved de ${uris.size} archivos guardados", Toast.LENGTH_SHORT).show()
                    finish()
                }
            } }
            return
        }
        val text = intent.getCharSequenceExtra(if (intent.action == Intent.ACTION_PROCESS_TEXT)
            Intent.EXTRA_PROCESS_TEXT else Intent.EXTRA_TEXT)?.toString().orEmpty()
        if (text.isNotBlank()) service.connection.publish(text) { success ->
            if (success) Toast.makeText(this, "Texto enviado al dock", Toast.LENGTH_SHORT).show()
            finish()
        } else finish()
    }

    override fun onDestroy() {
        if (bound) { unbindService(binding); bound = false }
        super.onDestroy()
    }
}
