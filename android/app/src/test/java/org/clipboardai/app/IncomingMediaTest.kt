package org.clipboardai.app

import android.content.ClipData
import android.content.Intent
import android.net.Uri
import android.os.Looper
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import android.content.ComponentName
import java.io.ByteArrayInputStream
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class IncomingMediaTest {
    @Test fun collectsPickerClipDataAndDeduplicatesFirstItem() {
        val first = Uri.parse("content://test/first")
        val second = Uri.parse("content://test/second")
        val result = Intent().setData(first).apply {
            clipData = ClipData.newRawUri("first", first).apply { addItem(ClipData.Item(second)) }
        }
        assertEquals(listOf(first, second), incomingUris(result))
    }

    @Test fun collectsEverySharedImage() {
        val first = Uri.parse("content://test/first")
        val second = Uri.parse("content://test/second")
        val share = Intent(Intent.ACTION_SEND_MULTIPLE).setType("image/png")
            .putParcelableArrayListExtra(Intent.EXTRA_STREAM, arrayListOf(first, second))
        assertEquals(listOf(first, second), incomingUris(share))
    }

    @Test fun sharesTwoImagesStraightIntoOfflineDock() {
        val app = RuntimeEnvironment.getApplication()
        val controller = Robolectric.buildService(DockService::class.java).create()
        val service = controller.get()
        shadowOf(app).setComponentNameAndServiceForBindService(
            ComponentName(app, DockService::class.java), service.onBind(Intent()))
        val first = Uri.parse("content://test/image-one.png")
        val second = Uri.parse("content://test/image-two.png")
        val expected = mapOf(first to byteArrayOf(1, 2, 3), second to byteArrayOf(4, 5, 6, 7))
        expected.forEach { (uri, bytes) ->
            shadowOf(app.contentResolver).registerInputStream(uri, ByteArrayInputStream(bytes))
        }
        val share = Intent(app, ShareReceiverActivity::class.java).setAction(Intent.ACTION_SEND_MULTIPLE)
            .setType("image/png").putParcelableArrayListExtra(Intent.EXTRA_STREAM, arrayListOf(first, second))
        val activity = Robolectric.buildActivity(ShareReceiverActivity::class.java, share).setup()
        try {
            var files: List<DockFile> = emptyList()
            val deadline = System.nanoTime() + 10_000_000_000L
            while (System.nanoTime() < deadline) {
                shadowOf(Looper.getMainLooper()).idle()
                service.connection.fileHistory { files = it }
                shadowOf(Looper.getMainLooper()).idle()
                if (files.size >= 2) break
                Thread.sleep(20)
            }
            assertEquals(2, files.size)
            assertEquals(listOf(3L, 4L), files.map { File(it.path).length() }.sorted())
            assertTrue(files.all { it.state == "pending" })
            assertTrue(files.all { it.item.getString("mime") == "image/png" })
            shadowOf(Looper.getMainLooper()).idle()
            assertTrue(activity.get().isFinishing)
        } finally {
            activity.pause().stop().destroy()
            controller.destroy()
        }
    }
}
