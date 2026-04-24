"""``edge_http`` TLS verify helper for Host → Edge clients."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from memoryagent.config_store import AppConfig
from memoryagent.edge_http import edge_httpx_verify


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
