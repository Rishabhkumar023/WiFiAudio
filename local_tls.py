"""Per-installation CA and per-address certificates for private LAN microphone use."""
import datetime as dt
import hashlib
import ipaddress
import ssl
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def prepare_tls(directory, addresses):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    ca_file, key_file = directory / "WiFiAudio-CA.crt", directory / "ca.key"
    now = dt.datetime.now(dt.timezone.utc)
    if ca_file.exists() != key_file.exists():
        raise ValueError("Incomplete local TLS identity. Restore the matching CA certificate/key backup.")
    if not ca_file.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "WiFiAudio local microphone CA")])
        ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
              .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5))
              .not_valid_after(now + dt.timedelta(days=1825))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
              .sign(key, hashes.SHA256()))
        with key_file.open("xb") as output:
            output.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
        with ca_file.open("xb") as output:
            output.write(ca.public_bytes(serialization.Encoding.PEM))
    else:
        ca = x509.load_pem_x509_certificate(ca_file.read_bytes())
        key = serialization.load_pem_private_key(key_file.read_bytes(), password=None)
    if key.public_key().public_numbers() != ca.public_key().public_numbers() or ca.not_valid_after_utc <= now:
        raise ValueError("Local CA is expired or does not match its key; restore a valid matching identity.")
    ips = sorted({str(ipaddress.ip_address(value)) for value in addresses} | {"127.0.0.1"})
    identity = hashlib.sha256((",".join(ips) + now.strftime("%Y-%m")).encode()).hexdigest()[:16]
    leaf_file, leaf_key_file = directory / f"server-{identity}.pem", directory / f"server-{identity}.key"
    if leaf_file.exists() != leaf_key_file.exists():
        raise ValueError("Incomplete local server certificate; restore its matching key/certificate backup.")
    if not leaf_file.exists():
        leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        leaf = (x509.CertificateBuilder()
                .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "WiFiAudio")]))
                .issuer_name(ca.subject).public_key(leaf_key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5))
                .not_valid_after(min(now + dt.timedelta(days=90), ca.not_valid_after_utc))
                .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip)) for ip in ips]
                                                          + [x509.DNSName("localhost")]), critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .sign(key, hashes.SHA256()))
        with leaf_key_file.open("xb") as output:
            output.write(leaf_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
        with leaf_file.open("xb") as output:
            output.write(leaf.public_bytes(serialization.Encoding.PEM))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(leaf_file, leaf_key_file)
    return context, ca_file, ca.fingerprint(hashes.SHA256()).hex(":")
