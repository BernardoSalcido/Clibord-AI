package org.clipboardai.app

import org.json.JSONObject
import java.util.UUID
import java.nio.CharBuffer

object Wire {
    const val MAX_TEXT = 256 * 1024
    const val MAX_MESSAGE = MAX_TEXT * 6 + 4096
    private fun utf8Size(text: String): Int = Charsets.UTF_8.newEncoder().encode(CharBuffer.wrap(text)).remaining()
    fun message(type: String) = JSONObject().put("v", 1).put("type", type)
    fun uuid(value: String): String {
        require(UUID.fromString(value).toString() == value) { "Identificador inválido" }
        return value
    }
    fun decode(text: String): JSONObject {
        require(utf8Size(text) <= MAX_MESSAGE) { "Mensaje demasiado grande" }
        val msg = JSONObject(text)
        require(msg.get("v") == 1) { "Versión incompatible" }
        msg.getString("type")
        return msg
    }
    fun item(value: JSONObject, expectedOrigin: String? = null): JSONObject {
        uuid(value.getString("id"))
        val origin = uuid(value.getString("origin"))
        require(expectedOrigin == null || origin == expectedOrigin) { "Origen incorrecto" }
        val number = value.get("seq")
        require(number is Int || number is Long) { "Secuencia inválida" }
        require(value.getLong("seq") in 1..9007199254740991L) { "Secuencia inválida" }
        require(value.getString("created").length <= 64) { "Fecha inválida" }
        utf8Size(value.getString("created"))
        val text = value.getString("text")
        require(text.isNotEmpty() && utf8Size(text) <= MAX_TEXT) {
            "El texto debe tener entre 1 byte y 256 KiB"
        }
        return JSONObject().apply {
            listOf("id", "origin", "created", "text").forEach { put(it, value.get(it)) }
            put("seq", value.getLong("seq"))
        }
    }
}
