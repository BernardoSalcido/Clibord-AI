package org.clipboardai.app

import android.content.Intent
import android.net.Uri

/** Collects every URI granted by a picker or Android Sharesheet, preserving selection order. */
internal fun incomingUris(intent: Intent?): List<Uri> {
    if (intent == null) return emptyList()
    val found = linkedSetOf<Uri>()
    intent.data?.let(found::add)
    if (intent.action == Intent.ACTION_SEND_MULTIPLE) {
        @Suppress("DEPRECATION")
        val many = intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)
        many?.forEach(found::add)
    } else if (intent.action == Intent.ACTION_SEND) {
        @Suppress("DEPRECATION")
        val one = intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM)
        one?.let(found::add)
    }
    intent.clipData?.let { clip ->
        for (index in 0 until clip.itemCount) clip.getItemAt(index).uri?.let(found::add)
    }
    return found.toList()
}
