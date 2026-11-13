package org.clipboardai.app

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class PairingDataTest {
    private val pin = "abcdef0123456789".repeat(4)
    private val code = "local_pairing_code_123456"
    private fun block() = JSONObject().put("v", 1).put("host", "192.168.1.10").put("port", 45821)
        .put("fingerprint", pin).put("code", code).toString()

    @Test fun acceptsCompleteBlockAndManualFieldsIdentically() {
        val parsed = PairingData.parse("\n  ${block()} \n")
        val manual = PairingData.fields(" 192.168.1.10 ", "45821", pin.uppercase().chunked(2).joinToString(":"), " $code ")
        assertEquals(parsed, manual)
    }
    @Test fun explainsWhyCodeAloneIsInsufficient() {
        val error = assertThrows(IllegalArgumentException::class.java) { PairingData.parse(code) }
        assertTrue(error.message!!.contains("bloque completo"))
        assertTrue(error.message!!.contains("Introducir datos"))
    }
    @Test fun rejectsMissingOrInvalidConnectionDetails() {
        assertThrows(IllegalArgumentException::class.java) { PairingData.parse("{\"code\":\"$code\"}") }
        assertThrows(IllegalArgumentException::class.java) { PairingData.parse("{invalid}") }
        assertThrows(IllegalArgumentException::class.java) { PairingData.fields("", "45821", pin, code) }
        assertThrows(IllegalArgumentException::class.java) { PairingData.fields("192.168.1.10", "0", pin, code) }
        assertThrows(IllegalArgumentException::class.java) { PairingData.fields("192.168.1.10", "45821", "", code) }
        assertThrows(IllegalArgumentException::class.java) { PairingData.fields("192.168.1.10", "45821", pin, "bad") }
    }
}
