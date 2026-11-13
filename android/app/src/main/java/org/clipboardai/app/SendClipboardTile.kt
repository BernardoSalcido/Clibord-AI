package org.clipboardai.app

import android.annotation.SuppressLint
import android.app.PendingIntent
import android.content.Intent
import android.os.Build
import android.service.quicksettings.TileService

/** A user tap opens a focused Activity; the tile itself cannot read Android's clipboard. */
class SendClipboardTile : TileService() {
    override fun onClick() {
        super.onClick()
        if (isLocked) unlockAndRun { launch() } else launch()
    }

    @SuppressLint("StartActivityAndCollapseDeprecated") // Required only on API 26–33.
    private fun launch() {
        val intent = Intent(this, SendClipboardActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (Build.VERSION.SDK_INT >= 34) {
            val pending = PendingIntent.getActivity(this, 0, intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            startActivityAndCollapse(pending)
        } else {
            @Suppress("DEPRECATION")
            startActivityAndCollapse(intent)
        }
    }
}
