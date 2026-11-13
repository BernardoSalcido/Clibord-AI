package org.clipboardai.app

import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.ConnectException
import java.net.UnknownHostException
import javax.net.ssl.SSLPeerUnverifiedException

class ConnectionFailureTest {
    @Test fun distinguishesUnavailableBrainFromBadAddressAndIdentity() {
        assertTrue(ConnectionFailure.message(RuntimeException(ConnectException())).contains("no acepta conexiones"))
        assertTrue(ConnectionFailure.message(UnknownHostException()).contains("dirección"))
        assertTrue(ConnectionFailure.message(SSLPeerUnverifiedException("pin mismatch")).contains("TLS"))
    }
}
