"""``edge_http`` TLS verify helper and SPKI pinning for Host → Edge clients."""

from __future__ import annotations

import ssl
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from memoryagent.config_store import AppConfig, normalize_edge_spki_pins_sha256
from memoryagent.edge_http import (
    PinningSSLContext,
    _PinningSSLObjectProxy,
    edge_httpx_verify,
    spki_sha256_hex_from_der_peer_cert,
)


def test_edge_httpx_verify_default_true() -> None:
    assert edge_httpx_verify(AppConfig()) is True


def test_edge_httpx_verify_insecure_false() -> None:
    cfg = replace(AppConfig(), edge_tls_insecure_skip_verify=True)
    assert edge_httpx_verify(cfg) is False


def test_edge_httpx_verify_ca_bundle_file(tmp_path: Path) -> None:
    pem = tmp_path / "ca.pem"
    pem.write_text("-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n")
    cfg = replace(AppConfig(), edge_tls_ca_bundle=str(pem))
    v = edge_httpx_verify(cfg)
    assert isinstance(v, str)
    assert v.endswith("ca.pem")


def test_edge_httpx_verify_missing_ca_bundle_falls_back_true(tmp_path: Path) -> None:
    cfg = replace(AppConfig(), edge_tls_ca_bundle=str(tmp_path / "nope.pem"))
    assert edge_httpx_verify(cfg) is True


def test_normalize_edge_spki_pins_sha256() -> None:
    assert normalize_edge_spki_pins_sha256(None) == []
    assert normalize_edge_spki_pins_sha256("bad") == []
    h = "ab" * 32
    h_colon = ":".join(h[i : i + 2] for i in range(0, len(h), 2))
    assert normalize_edge_spki_pins_sha256([h, h_colon]) == [h, h]


def test_spki_sha256_hex_stable_for_cert() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "spki-pin-test")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    der = cert.public_bytes(serialization.Encoding.DER)
    a = spki_sha256_hex_from_der_peer_cert(der)
    b = spki_sha256_hex_from_der_peer_cert(der)
    assert a == b
    assert len(a) == 64


def test_edge_httpx_verify_with_pins_returns_ssl_context() -> None:
    cfg = replace(AppConfig(), edge_tls_spki_pins_sha256=["cd" * 32])
    v = edge_httpx_verify(cfg)
    assert isinstance(v, ssl.SSLContext)
    assert isinstance(v, PinningSSLContext)


def test_pinning_proxy_rejects_spki_not_in_set() -> None:
    key1 = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key2 = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def _self_signed(k: rsa.RSAPrivateKey, cn: str) -> bytes:
        subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(k.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=2))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(k, hashes.SHA256())
        )
        return cert.public_bytes(serialization.Encoding.DER)

    der1 = _self_signed(key1, "one")
    der2 = _self_signed(key2, "two")
    pin_ok = spki_sha256_hex_from_der_peer_cert(der1)

    inner = MagicMock()
    inner.do_handshake = MagicMock()
    inner.getpeercert.side_effect = lambda binary_form=False: der2 if binary_form else {}

    proxy = _PinningSSLObjectProxy(inner, frozenset({pin_ok}))
    with pytest.raises(ssl.SSLError, match="pinning failed"):
        proxy.do_handshake()
