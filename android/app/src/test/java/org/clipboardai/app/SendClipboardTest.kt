package org.clipboardai.app

import android.content.ClipData
import android.net.Uri
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class SendClipboardTest {
    @Test fun plainTextKeepsLineBreaksAndSymbols() {
        val result = clipboardContent(ClipData.newPlainText("text", "Línea 1\n\$x\$"))
        assertEquals("Línea 1\n\$x\$", (result as ClipboardContent.Text).value)
    }

    @Test fun copiedImageUriIsQueuedAsFileInsteadOfUriText() {
        val uri = Uri.parse("content://example.test/image/42")
        val result = clipboardContent(ClipData.newRawUri("image", uri))
        assertEquals(uri, (result as ClipboardContent.File).uri)
    }

    @Test fun multipleCopiedImagesStayInSelectionOrder() {
        val first = Uri.parse("content://example.test/one.png")
        val second = Uri.parse("content://example.test/two.png")
        val clip = ClipData.newRawUri("images", first).apply { addItem(ClipData.Item(second)) }
        assertEquals(listOf(first, second), clipboardUris(clip))
    }

    @Test fun emptyTextDoesNotCreateAnItem() {
        assertNull(clipboardContent(ClipData.newPlainText("text", "   ")))
    }
}
