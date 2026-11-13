"""TLS identity and short-lived, one-use pairing secret."""
import hashlib
import secrets
import ssl
import time
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def tls_identity(directory):
    cert_file, key_file = directory / "server.pem", directory / "server-key.pem"
    if not cert_file.exists() or not key_file.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Clipboard AI")])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=3650))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .sign(key, hashes.SHA256()))
        key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                             serialization.PrivateFormat.PKCS8,
                                             serialization.NoEncryption()))
        key_file.chmod(0o600)
        cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    cert = x509.load_pem_x509_certificate(cert_file.read_bytes())
    fingerprint = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert_file, key_file)
    return context, fingerprint


class Pairing:
    def __init__(self):
        self.code = None
        self.deadline = 0
        self.attempts = 0

    def open(self):
        self.code = secrets.token_urlsafe(18)
        self.deadline = time.monotonic() + 300
        self.attempts = 0
        return self.code

    def consume(self, code):
        self.attempts += 1
        valid = (self.code is not None and time.monotonic() < self.deadline and self.attempts <= 5
                 and isinstance(code, str) and secrets.compare_digest(self.code, code))
        if valid or self.attempts >= 5 or time.monotonic() >= self.deadline:
            self.code = None
        return bool(valid)
