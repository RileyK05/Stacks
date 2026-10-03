"""The add-in's local HTTPS certificate.

A fresh CA signs one ``localhost`` server certificate and its private key is
then thrown away: Windows is asked to trust a CA that can never sign
anything else, so trusting it cannot be abused to intercept other sites.
Renewing means issuing a new pair (and one more trust prompt).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

LIFETIME = dt.timedelta(days=825)
RENEW_BEFORE = dt.timedelta(days=30)
CA_COMMON_NAME = "Stacks local add-in (this computer only)"


@dataclass(frozen=True)
class CertPaths:
    cert: Path
    key: Path
    ca: Path

    @classmethod
    def in_dir(cls, folder: Path) -> CertPaths:
        return cls(
            cert=folder / "localhost.pem",
            key=folder / "localhost-key.pem",
            ca=folder / "stacks-local-ca.cer",
        )

    def exist(self) -> bool:
        return self.cert.is_file() and self.key.is_file() and self.ca.is_file()


def issue(folder: Path, *, now: dt.datetime | None = None) -> CertPaths:
    """Write a new CA (DER, public only) and a signed localhost cert + key."""
    now = now or dt.datetime.now(dt.UTC)
    folder.mkdir(parents=True, exist_ok=True)
    paths = CertPaths.in_dir(folder)

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CA_COMMON_NAME)])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + LIFETIME + dt.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + LIFETIME)
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                    x509.IPAddress(ipaddress.ip_address("::1")),
                ]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    del ca_key

    _atomic_write(
        paths.key,
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )
    _atomic_write(
        paths.cert,
        leaf.public_bytes(serialization.Encoding.PEM)
        + ca.public_bytes(serialization.Encoding.PEM),
    )
    _atomic_write(paths.ca, ca.public_bytes(serialization.Encoding.DER))
    return paths


def _atomic_write(path: Path, data: bytes) -> None:
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def is_current(paths: CertPaths, *, now: dt.datetime | None = None) -> bool:
    """The files exist, the leaf was signed by this CA, and it is not about
    to expire."""
    if not paths.exist():
        return False
    now = now or dt.datetime.now(dt.UTC)
    try:
        leaf = x509.load_pem_x509_certificate(paths.cert.read_bytes())
        ca = x509.load_der_x509_certificate(paths.ca.read_bytes())
        key = serialization.load_pem_private_key(paths.key.read_bytes(), password=None)
        leaf.verify_directly_issued_by(ca)
        if key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        ) != leaf.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        ):
            return False
    except (OSError, ValueError, TypeError, InvalidSignature):
        return False
    return leaf.not_valid_before_utc <= now < leaf.not_valid_after_utc - RENEW_BEFORE


def ca_der(paths: CertPaths) -> bytes:
    return paths.ca.read_bytes()


def ca_thumbprint(paths: CertPaths) -> str:
    """The SHA-1 thumbprint Windows' certificate tools identify a cert by."""
    return hashlib.sha1(ca_der(paths), usedforsecurity=False).hexdigest().upper()
