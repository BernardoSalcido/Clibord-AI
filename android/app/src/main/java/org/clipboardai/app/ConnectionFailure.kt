package org.clipboardai.app

import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.security.cert.CertificateException
import javax.net.ssl.SSLPeerUnverifiedException

/** Converts connection failures to actionable statuses without including pairing secrets. */
internal object ConnectionFailure {
    fun message(error: Throwable): String {
        val causes = generateSequence(error) { it.cause }.take(12).toList()
        return when {
            causes.any { it is CertificateException || it is SSLPeerUnverifiedException } ->
                "La identidad TLS del cerebro no coincide. Comprueba la vinculación."
            causes.any { it is UnknownHostException } ->
                "No se encuentra la dirección del cerebro. Comprueba la IP o el nombre de red."
            causes.any { it is ConnectException } ->
                "El cerebro no acepta conexiones. Abre Clipboard AI en el ordenador y comprueba el puerto."
            causes.any { it is NoRouteToHostException } ->
                "No hay ruta hacia el cerebro. Comprueba la red o la VPN."
            causes.any { it is SocketTimeoutException } ->
                "El cerebro no responde a tiempo. Comprueba la red, la VPN y el firewall."
            else -> "No se pudo conectar al cerebro. Comprueba la red y vuelve a intentar."
        }
    }
}
