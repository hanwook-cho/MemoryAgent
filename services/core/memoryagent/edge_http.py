"""Shared TLS / httpx ``verify`` settings for Host → Edge HTTP clients (MP1)."""

from __future__ import annotations

import hashlib
import logging
import ssl
from pathlib import Path
from typing import Any

from memoryagent.config_store import AppConfig, normalize_edge_spki_pins_sha256

logger = logging.getLogger(__name__)

# ``httpx`` / ``httpcore`` accept ``bool``, ``str`` (CA path), or ``ssl.SSLContext``.
SslVerifyArg = bool | str | ssl.SSLContext


def spki_sha256_hex_from_der_peer_cert(der: bytes) -> str:
    """
    SHA-256 hex digest of the leaf certificate's **SubjectPublicKeyInfo** (SPKI) DER.

    Matches ``openssl x509 -in cert.pem -noout -pubkey | openssl pkey -pubin -outform der | openssl dgst -sha256``.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    cert = x509.load_der_x509_certificate(der)
    spki = cert.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(spki).hexdigest()


class _PinningSSLObjectProxy:
    """Wrap ``ssl.SSLObject`` so SPKI is checked immediately after a successful handshake."""

    __slots__ = ("_inner", "_pins_hex")

    def __init__(self, inner: ssl.SSLObject, pins_hex: frozenset[str]) -> None:
        self._inner = inner
        self._pins_hex = pins_hex

    def do_handshake(self, *args: Any, **kwargs: Any) -> None:
        self._inner.do_handshake(*args, **kwargs)
        der = self._inner.getpeercert(binary_form=True)
        if not der:
            raise ssl.SSLError("TLS pinning: no peer certificate after handshake")
        got = spki_sha256_hex_from_der_peer_cert(der)
        if got not in self._pins_hex:
            raise ssl.SSLError(
                "TLS certificate pinning failed: leaf SPKI SHA-256 "
                f"{got} is not in edge_tls_spki_pins_sha256"
            )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class PinningSSLContext(ssl.SSLContext):
    """
    ``ssl.SSLContext`` that enforces SPKI (public key) pins after the TLS handshake.

    AnyIO may call ``wrap_bio`` on a worker thread when the type is not exactly
    ``ssl.SSLContext``; this remains compatible.

    ``pins_hex`` is keyword-only. ``ssl.SSLContext`` is allocated via ``__new__``
    (its ``__init__`` is not used the same way as plain Python subclasses).
    """

    __slots__ = ("_pins_hex",)

    def __new__(
        cls,
        *,
        pins_hex: frozenset[str],
        protocol: int = ssl.PROTOCOL_TLS_CLIENT,
    ) -> PinningSSLContext:
        self = super().__new__(cls, protocol)
        self._pins_hex = pins_hex
        return self  # type: ignore[return-value]

    def wrap_bio(
        self,
        incoming: ssl.MemoryBIO,
        outgoing: ssl.MemoryBIO,
        server_side: bool = False,
        server_hostname: str | None = None,
        session: ssl.SSLSession | None = None,
    ) -> ssl.SSLObject:
        inner = super().wrap_bio(
            incoming,
            outgoing,
            server_side=server_side,
            server_hostname=server_hostname,
            session=session,
        )
        return _PinningSSLObjectProxy(inner, self._pins_hex)  # type: ignore[return-value]  # duck-types as SSLObject


def edge_httpx_verify(cfg: AppConfig) -> SslVerifyArg:
    """
    Return ``httpx`` ``verify`` argument for edge requests.

    - ``edge_tls_insecure_skip_verify``: disable verification (dev only; logs warning).
      SPKI pins are **not** enforced in this mode.
    - ``edge_tls_spki_pins_sha256``: non-empty list → ``PinningSSLContext`` (SPKI pin
      after successful handshake; uses ``edge_tls_ca_bundle`` or certifi for CA trust).
    - ``edge_tls_ca_bundle``: path to PEM CA bundle when set and the file exists.
    - Otherwise: ``True`` (system / default trust store).
    """
    if getattr(cfg, "edge_tls_insecure_skip_verify", False):
        pins = normalize_edge_spki_pins_sha256(
            getattr(cfg, "edge_tls_spki_pins_sha256", []) or []
        )
        if pins:
            logger.warning(
                "edge_tls_spki_pins_sha256 is set but ignored because "
                "edge_tls_insecure_skip_verify is true"
            )
        logger.warning(
            "edge_tls_insecure_skip_verify is true; TLS certificate verification is disabled for edge"
        )
        return False
    pins = normalize_edge_spki_pins_sha256(
        getattr(cfg, "edge_tls_spki_pins_sha256", []) or []
    )
    if pins:
        import certifi

        ctx = PinningSSLContext(
            pins_hex=frozenset(pins),
            protocol=ssl.PROTOCOL_TLS_CLIENT,
        )
        ca = getattr(cfg, "edge_tls_ca_bundle", None)
        if ca and isinstance(ca, str) and ca.strip():
            p = Path(ca).expanduser()
            if p.is_file():
                ctx.load_verify_locations(cafile=str(p.resolve()))
            else:
                logger.warning(
                    "edge_tls_ca_bundle is not a readable file (%s); using certifi for pin context",
                    ca,
                )
                ctx.load_verify_locations(cafile=certifi.where())
        else:
            ctx.load_verify_locations(cafile=certifi.where())
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        return ctx
    raw = getattr(cfg, "edge_tls_ca_bundle", None)
    if raw:
        p = Path(str(raw)).expanduser()
        if p.is_file():
            return str(p.resolve())
        logger.warning("edge_tls_ca_bundle is not a readable file (%s); using default verify", raw)
    return True


def edge_mapped_file_ingest_path(
    host_path: Path,
    *,
    host_root: Path | None,
    edge_root: str | None,
) -> str | None:
    """
    Map a host-resolved file path to a Node-local path for ``POST /ingest`` ``kind=file``.

    Both ``host_root`` and ``edge_root`` must be set; otherwise returns ``None``.
    """
    if host_root is None or not edge_root or not str(edge_root).strip():
        return None
    try:
        rel = host_path.expanduser().resolve().relative_to(host_root)
    except ValueError:
        return None
    er = str(edge_root).strip().rstrip("/")
    return f"{er}/{rel.as_posix()}"


def resolved_edge_path_host_root(cfg: AppConfig) -> Path | None:
    """Return resolved directory prefix for host-side path mapping, or ``None``."""
    raw = getattr(cfg, "edge_ingest_path_host_prefix", None)
    if not raw or not str(raw).strip():
        return None
    p = Path(str(raw)).expanduser()
    try:
        return p.resolve()
    except OSError:
        logger.warning("edge_ingest_path_host_prefix could not be resolved: %s", raw)
        return None
