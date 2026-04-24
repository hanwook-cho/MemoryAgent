"""Load and persist `config.json` under the data directory."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

KNOWN_DEPLOYMENT_MODES = frozenset(
    {"standalone", "host_edge", "hybrid", "ios_companion"}
)


def normalize_edge_base_url(raw: Any) -> str | None:
    """Return stripped ``https?://`` URL or ``None``; invalid values become ``None``."""
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        logger.warning("edge_base_url ignored (not a string): %r", raw)
        return None
    s = raw.strip()
    if not s:
        return None
    lower = s.lower()
    if not (lower.startswith("http://") or lower.startswith("https://")):
        logger.warning("edge_base_url must start with http:// or https://; got %r", raw)
        return None
    return s.rstrip("/")


def normalize_deployment_mode(raw: Any) -> str:
    """Return a valid ``deployment_mode``; unknown legacy values fall back to ``standalone``."""
    if raw is None or raw == "":
        return "standalone"
    if not isinstance(raw, str):
        logger.warning(
            "deployment_mode ignored (not a string): %r; using standalone", raw
        )
        return "standalone"
    if raw not in KNOWN_DEPLOYMENT_MODES:
        logger.warning("deployment_mode unknown: %r; using standalone", raw)
        return "standalone"
    return raw


def _default_ignore_globs() -> list[str]:
    return ["**/.git/**", "**/node_modules/**", "**/.DS_Store"]


def optional_config_string(raw: Any) -> str | None:
    """Normalize optional JSON string fields (``None`` / empty → ``None``)."""
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    return s or None


def normalize_edge_spki_pins_sha256(raw: Any) -> list[str]:
    """
    Normalize ``edge_tls_spki_pins_sha256`` from JSON: list of 64-char hex strings
    (optional ``:`` separators stripped). Invalid entries are skipped with a warning.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        logger.warning("edge_tls_spki_pins_sha256 ignored (not a list): %r", raw)
        return []
    out: list[str] = []
    for i, x in enumerate(raw):
        if not isinstance(x, str):
            logger.warning("edge_tls_spki_pins_sha256[%s] ignored (not a string)", i)
            continue
        h = x.strip().lower().replace(":", "")
        if len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
            logger.warning(
                "edge_tls_spki_pins_sha256[%s] ignored (expected 64 hex chars): %r",
                i,
                x,
            )
            continue
        out.append(h)
    return out


@dataclass
class AppConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    chat_model: str = "llama3.2"
    embed_model: str = "nomic-embed-text"
    ollama_base_url: str = "http://127.0.0.1:11434"
    watched_roots: list[str] = field(default_factory=list)
    watch_ignore_globs: list[str] = field(default_factory=_default_ignore_globs)
    watch_debounce_seconds: float = 1.5
    deployment_mode: str = "standalone"
    edge_base_url: str | None = None
    # Edge TLS (httpx verify=): optional PEM CA bundle; insecure skip for lab only.
    edge_tls_ca_bundle: str | None = None
    edge_tls_insecure_skip_verify: bool = False
    # When both set, host files under host_prefix map to edge paths for POST /ingest kind=file.
    edge_ingest_path_host_prefix: str | None = None
    edge_ingest_path_edge_prefix: str | None = None
    # SPKI SHA-256 pins (hex, 64 chars each); enforced on edge HTTPS after CA validation.
    edge_tls_spki_pins_sha256: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AppConfig:
        wr = d.get("watched_roots")
        ig = d.get("watch_ignore_globs")
        insecure = d.get("edge_tls_insecure_skip_verify", False)
        return cls(
            host=d.get("host", cls.host),
            port=int(d.get("port", cls.port)),
            chat_model=d.get("chat_model", cls.chat_model),
            embed_model=d.get("embed_model", cls.embed_model),
            ollama_base_url=d.get("ollama_base_url", cls.ollama_base_url),
            watched_roots=list(wr) if isinstance(wr, list) else [],
            watch_ignore_globs=list(ig) if isinstance(ig, list) else _default_ignore_globs(),
            watch_debounce_seconds=float(d.get("watch_debounce_seconds", 1.5)),
            deployment_mode=normalize_deployment_mode(d.get("deployment_mode")),
            edge_base_url=normalize_edge_base_url(d.get("edge_base_url")),
            edge_tls_ca_bundle=optional_config_string(d.get("edge_tls_ca_bundle")),
            edge_tls_insecure_skip_verify=bool(insecure),
            edge_ingest_path_host_prefix=optional_config_string(
                d.get("edge_ingest_path_host_prefix")
            ),
            edge_ingest_path_edge_prefix=optional_config_string(
                d.get("edge_ingest_path_edge_prefix")
            ),
            edge_tls_spki_pins_sha256=normalize_edge_spki_pins_sha256(
                d.get("edge_tls_spki_pins_sha256")
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "chat_model": self.chat_model,
            "embed_model": self.embed_model,
            "ollama_base_url": self.ollama_base_url,
            "watched_roots": list(self.watched_roots),
            "watch_ignore_globs": list(self.watch_ignore_globs),
            "watch_debounce_seconds": self.watch_debounce_seconds,
            "deployment_mode": self.deployment_mode,
        }
        if self.edge_base_url:
            d["edge_base_url"] = self.edge_base_url
        else:
            d["edge_base_url"] = None
        if self.edge_tls_ca_bundle:
            d["edge_tls_ca_bundle"] = self.edge_tls_ca_bundle
        else:
            d["edge_tls_ca_bundle"] = None
        d["edge_tls_insecure_skip_verify"] = self.edge_tls_insecure_skip_verify
        d["edge_ingest_path_host_prefix"] = self.edge_ingest_path_host_prefix
        d["edge_ingest_path_edge_prefix"] = self.edge_ingest_path_edge_prefix
        d["edge_tls_spki_pins_sha256"] = list(self.edge_tls_spki_pins_sha256)
        return d


def config_path(data_dir: Path) -> Path:
    return data_dir / "config.json"


def load_config(data_dir: Path) -> AppConfig:
    path = config_path(data_dir)
    if not path.is_file():
        cfg = AppConfig()
        save_config(data_dir, cfg)
        return cfg
    with path.open(encoding="utf-8") as f:
        return AppConfig.from_dict(json.load(f))


def save_config(data_dir: Path, cfg: AppConfig) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = config_path(data_dir)
    with path.open("w", encoding="utf-8") as f:
        json.dump(cfg.to_dict(), f, indent=2)
        f.write("\n")
