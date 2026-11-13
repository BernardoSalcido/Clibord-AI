package org.clipboardai.app

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.File

class WireTest {
    private fun fixture(): JSONObject = Wire.decode(File("../../protocol/fixtures/unicode.json").readText())

    @Test fun unicodeFixtureAndRoundTrip() {
        val msg = fixture()
        val item = Wire.item(msg.getJSONObject("item"))
        assertEquals("  áéíóú ñ μ Δ 中文 🧪\nsegunda línea\n ", item.getString("text"))
        val again = Wire.item(Wire.decode(Wire.message("item").put("item", item).toString()).getJSONObject("item"))
        assertEquals(item.toString(), again.toString())
        assertEquals(1L, again.getLong("seq"))
    }
    @Test fun rejectsInvalidInputs() {
        val original = fixture().getJSONObject("item")
        for (change in listOf("", "é".repeat(Wire.MAX_TEXT / 2 + 1))) {
            assertThrows(IllegalArgumentException::class.java) {
                Wire.item(JSONObject(original.toString()).put("text", change))
            }
        }
        assertThrows(IllegalArgumentException::class.java) { Wire.item(original, "another-origin") }
        assertThrows(IllegalArgumentException::class.java) { Wire.item(JSONObject(original.toString()).put("seq", true)) }
        assertThrows(IllegalArgumentException::class.java) { Wire.decode("{\"v\":2,\"type\":\"ready\"}") }
        assertThrows(java.nio.charset.CharacterCodingException::class.java) {
            Wire.item(JSONObject(original.toString()).put("text", "\uD800"))
        }
        assertThrows(IllegalArgumentException::class.java) { PinnedTls.client("bad") }
    }
}
