package org.clipboardai.app

import org.json.JSONException
import org.json.JSONObject

/** Validate scanned and manual data identically, before starting a connection. */
data class PairingData(val host: String, val port: Int, val fingerprint: String, val code: String) {
    companion object {
        fun endpoint(host: String, port: String): Pair<String, Int> {
            val address = host.trim()
            require(address.matches(Regex("[A-Za-z0-9.:-]{1,253}"))) { "Introduce una dirección IP o nombre válido del cerebro." }
            val number = port.trim().toIntOrNull()
            require(number != null && number in 1..65535) { "El puerto debe estar entre 1 y 65535." }
            return address to number
        }
        fun fields(host: String, port: String, fingerprint: String, code: String): PairingData {
            val (address, number) = endpoint(host, port)
            val pin = fingerprint.filterNot { it.isWhitespace() || it == ':' }.lowercase()
            require(pin.matches(Regex("[a-f0-9]{64}"))) { "Falta la huella de seguridad completa: son 64 caracteres, junto al QR del ordenador." }
            val secret = code.trim()
            require(secret.matches(Regex("[A-Za-z0-9_-]{16,128}"))) { "Introduce el código temporal completo que muestra el ordenador." }
            return PairingData(address, number, pin, secret)
        }

        fun parse(text: String): PairingData {
            val value = text.trim()
            require(value.startsWith("{")) {
                "Aquí debes pegar el bloque completo, desde { hasta }. Si solo tienes el código, usa Introducir datos y completa también la dirección y la huella."
            }
            require(value.toByteArray(Charsets.UTF_8).size <= 4096) { "Los datos de vinculación son demasiado largos." }
            try {
                val data = JSONObject(value)
                require(data.get("v") == 1) { "Versión de vinculación incompatible." }
                return fields(data.getString("host"), data.getInt("port").toString(),
                    data.getString("fingerprint"), data.getString("code"))
            } catch (_: JSONException) {
                throw IllegalArgumentException("El bloque está incompleto o no es válido. Copia desde { hasta }, o usa Introducir datos.")
            }
        }
    }
}
