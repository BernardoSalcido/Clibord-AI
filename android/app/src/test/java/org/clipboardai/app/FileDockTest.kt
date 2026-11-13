package org.clipboardai.app

import android.content.Context
import androidx.core.content.FileProvider
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.io.ByteArrayInputStream
import java.io.File
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class FileDockTest {
    private fun dock(): FileDock = FileDock(RuntimeEnvironment.getApplication(), UUID.randomUUID().toString())
    private fun incoming(data: ByteArray, peer: String, name: String = "árbol 🧪.bin"): JSONObject {
        val file = File(RuntimeEnvironment.getApplication().cacheDir, UUID.randomUUID().toString()).apply { writeBytes(data) }
        return JSONObject().put("id", UUID.randomUUID().toString()).put("origin", peer).put("created", "2026-10-16")
            .put("name", name).put("size", data.size).put("sha256", FileDock.digest(file)).put("mime", "application/octet-stream")
            .also { file.delete() }
    }
    private fun chunk(id: String, data: ByteArray, offset: Long = 0) = Wire.message("file_chunk").put("id", id)
        .put("offset", offset).put("data", android.util.Base64.encodeToString(data, android.util.Base64.NO_WRAP))

    @Test fun acceptsImageRelayedByPinnedBrainFromAnotherPhone() {
        val brain = UUID.randomUUID().toString()
        val source = UUID.randomUUID().toString()
        val dock = dock()
        try {
            val bytes = byteArrayOf(1, 2, 3)
            val image = incoming(bytes, source, "Screenshot.png").put("mime", "image/png")
            val offer = Wire.message("file_offer").put("file", image)
            assertThrows(IllegalArgumentException::class.java) { dock.handle(offer, brain) }
            assertEquals("file_accept", dock.handle(offer, brain, relayed = true)!!.getString("type"))
            assertEquals("file_done", dock.handle(chunk(image.getString("id"), bytes), brain, relayed = true)!!.getString("type"))
            assertArrayEquals(bytes, File(dock.get(image.getString("id")).path).readBytes())
        } finally { dock.close() }
    }

    @Test fun receiveResumeAcrossDatabaseReopenAndShareWithProvider() {
        val peer = UUID.randomUUID().toString()
        val content = ByteArray(FileDock.CHUNK + 9) { (it % 251).toByte() }
        val item = incoming(content, peer)
        var dock = dock()
        try {
            val offer = Wire.message("file_offer").put("file", item)
            assertEquals(0, dock.handle(offer, peer)!!.getLong("offset"))
            val first = chunk(item.getString("id"), content.copyOfRange(0, FileDock.CHUNK))
            assertEquals(FileDock.CHUNK.toLong(), dock.handle(first, peer)!!.getLong("offset"))
            assertEquals(FileDock.CHUNK.toLong(), dock.handle(first, peer)!!.getLong("offset"))
            dock.close(); dock = dock()
            assertEquals(FileDock.CHUNK.toLong(), dock.handle(offer, peer)!!.getLong("offset"))
            assertEquals("file_done", dock.handle(chunk(item.getString("id"), content.copyOfRange(FileDock.CHUNK, content.size), FileDock.CHUNK.toLong()), peer)!!.getString("type"))
            val row = dock.get(item.getString("id"))
            assertArrayEquals(content, File(row.path).readBytes())
            val app = RuntimeEnvironment.getApplication()
            val provider = app.packageManager.resolveContentProvider("${app.packageName}.files", android.content.pm.PackageManager.GET_META_DATA)!!
            assertFalse(provider.exported); assertTrue(provider.grantUriPermissions)
            assertTrue(provider.metaData.getInt("android.support.FILE_PROVIDER_PATHS") != 0)
            // AndroidX's path strategy hardcodes '/', while Robolectric on Windows returns '\\'.
            // Inspect the real provider declaration here; exercise URI traversal on Unix hosts.
            if (File.separatorChar == '/') {
                val uri = FileProvider.getUriForFile(app, "${app.packageName}.files", File(row.path))
                assertArrayEquals(content, app.contentResolver.openInputStream(uri)!!.use { it.readBytes() })
            }
            dock.delete(row.id)
            assertEquals("file_done", dock.handle(offer, peer)!!.getString("type"))
            assertFalse(File(row.path).exists())
        } finally { dock.close() }
    }

    @Test fun immutableOutgoingCopyAndCleanupPreserveOriginal() {
        val dock = dock()
        try {
            val original = File(dock.root, "original.bin").apply { writeBytes(byteArrayOf(1, 2, 3)) }
            val item = dock.commitPrepared(dock.prepare(original.inputStream(), "original.bin", "application/octet-stream"))
            original.writeBytes(byteArrayOf(9))
            val response = dock.handle(Wire.message("file_accept").put("id", item.getString("id")).put("offset", 0), UUID.randomUUID().toString())!!
            assertArrayEquals(byteArrayOf(1, 2, 3), android.util.Base64.decode(response.getString("data"), 0))
            dock.handle(Wire.message("file_done").put("id", item.getString("id")), UUID.randomUUID().toString())
            assertEquals(1 to 3L, dock.deliveredUsage())
            dock.clearDelivered()
            assertEquals(0 to 0L, dock.deliveredUsage())
            assertArrayEquals(byteArrayOf(9), original.readBytes())
        } finally { dock.close() }
    }

    @Test fun zeroLengthAndDuplicateNamesDoNotOverwrite() {
        val dock = dock(); val peer = UUID.randomUUID().toString()
        try {
            val first = incoming(byteArrayOf(), peer, "same.pdf")
            assertEquals("file_done", dock.handle(Wire.message("file_offer").put("file", first), peer)!!.getString("type"))
            val second = incoming(byteArrayOf(), peer, "same.pdf")
            dock.handle(Wire.message("file_offer").put("file", second), peer)
            assertNotEquals(dock.get(first.getString("id")).path, dock.get(second.getString("id")).path)
        } finally { dock.close() }
    }

    @Test fun corruptionAndCancellationCannotReappear() {
        val dock = dock(); val peer = UUID.randomUUID().toString()
        try {
            val item = incoming(byteArrayOf(1), peer)
            val offer = Wire.message("file_offer").put("file", item)
            dock.handle(offer, peer)
            assertThrows(IllegalArgumentException::class.java) { dock.handle(chunk(item.getString("id"), byteArrayOf(2)), peer) }
            dock.cancel(item.getString("id")); dock.delete(item.getString("id"))
            assertTrue(dock.history().isEmpty())
            assertEquals("file_cancel", dock.handle(offer, peer)!!.getString("type"))
            val second = incoming(byteArrayOf(1), peer)
            dock.handle(Wire.message("file_cancel").put("id", second.getString("id")), peer)
            assertEquals("file_cancel", dock.handle(Wire.message("file_offer").put("file", second), peer)!!.getString("type"))
        } finally { dock.close() }
    }

    @Test fun rejectPathsOversizeWrongOriginAndOffsets() {
        val peer = UUID.randomUUID().toString(); val dock = dock()
        try {
            for (name in listOf("../a", "C:\\a", "NUL.txt", "a/b", "bad.", "a\n")) {
                assertThrows(IllegalArgumentException::class.java) { FileDock.metadata(incoming(byteArrayOf(1), peer, name), peer) }
            }
            val item = incoming(byteArrayOf(1), peer)
            assertThrows(IllegalArgumentException::class.java) { FileDock.metadata(JSONObject(item.toString()).put("size", FileDock.MAX_FILE + 1), peer) }
            assertThrows(IllegalArgumentException::class.java) { FileDock.metadata(item, UUID.randomUUID().toString()) }
            dock.handle(Wire.message("file_offer").put("file", item), peer)
            assertThrows(IllegalArgumentException::class.java) { dock.handle(chunk(item.getString("id"), byteArrayOf(1), -1), peer) }
            assertThrows(IllegalArgumentException::class.java) { dock.capacity(FileDock.QUOTA + 1) }
        } finally { dock.close() }
    }
}
