package org.clipboardai.app

import android.annotation.SuppressLint
import okhttp3.OkHttpClient
import java.security.MessageDigest
import java.security.SecureRandom
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

object PinnedTls {
    // Private LAN identity is established by out-of-band SHA-256 pin, not a public CA.
    // Validity and exact leaf identity are checked; the negative-pin integration test
    // verifies rejection. This trust manager is scoped to this one client instance.
    @SuppressLint("CustomX509TrustManager")
    fun client(fingerprint: String): OkHttpClient {
        require(fingerprint.matches(Regex("[a-fA-F0-9]{64}"))) { "Huella TLS inválida" }
        val pin = fingerprint.lowercase()
        val trust = object : X509TrustManager {
            override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
            override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {
                throw CertificateException("Solo se admite servidor")
            }
            override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
                if (chain.isEmpty()) throw CertificateException("Falta certificado")
                chain[0].checkValidity()
                val actual = MessageDigest.getInstance("SHA-256").digest(chain[0].encoded)
                    .joinToString("") { "%02x".format(it.toInt() and 255) }
                if (!MessageDigest.isEqual(actual.toByteArray(), pin.toByteArray()))
                    throw CertificateException("La identidad del ordenador ha cambiado")
            }
        }
        val ssl = SSLContext.getInstance("TLS")
        ssl.init(null, arrayOf<TrustManager>(trust), SecureRandom())
        return OkHttpClient.Builder().sslSocketFactory(ssl.socketFactory, trust)
            // This instance trusts exactly the pinned certificate, regardless of LAN IP.
            // A separate default client is never modified.
            .hostnameVerifier { _, session ->
                val cert = session.peerCertificates.firstOrNull() as? X509Certificate
                cert != null && MessageDigest.getInstance("SHA-256").digest(cert.encoded)
                    .joinToString("") { "%02x".format(it.toInt() and 255) } == pin
            }
            .connectTimeout(10, TimeUnit.SECONDS).readTimeout(0, TimeUnit.SECONDS)
            .pingInterval(20, TimeUnit.SECONDS).build()
    }
}
