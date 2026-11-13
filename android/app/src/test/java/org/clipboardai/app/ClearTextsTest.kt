package org.clipboardai.app

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class ClearTextsTest {
    @Test fun clearsPendingAndDeliveredLocallyButKeepsReplayReceipts() {
        val context = RuntimeEnvironment.getApplication()
        context.deleteDatabase("dock.db")
        val store = DockStore(context)
        try {
            store.create("pending")
            val server = UUID.randomUUID().toString()
            val remote = JSONObject().put("id", UUID.randomUUID().toString())
                .put("origin", server).put("seq", 1).put("created", "2026-11-12T00:00:00Z")
                .put("text", "delivered")
            assertTrue(store.receive(remote, server))
            assertEquals(2 to 1, store.textUsage())
            assertEquals(2, store.clearTexts())
            assertEquals(0 to 0, store.textUsage())
            assertFalse(store.receive(remote, server))
            assertTrue(store.history().isEmpty())
        } finally { store.close(); context.deleteDatabase("dock.db") }
    }
}
