"""Load and persist `config.json` under the data directory."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _default_ignore_globs() -> list[str]:
    return ["**/.git/**", "**/node_modules/**", "**/.DS_Store"]


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

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AppConfig:
        wr = d.get("watched_roots")
        ig = d.get("watch_ignore_globs")
        return cls(
            host=d.get("host", cls.host),
            port=int(d.get("port", cls.port)),
            chat_model=d.get("chat_model", cls.chat_model),
            embed_model=d.get("embed_model", cls.embed_model),
            ollama_base_url=d.get("ollama_base_url", cls.ollama_base_url),
            watched_roots=list(wr) if isinstance(wr, list) else [],
            watch_ignore_globs=list(ig) if isinstance(ig, list) else _default_ignore_globs(),
            watch_debounce_seconds=float(d.get("watch_debounce_seconds", 1.5)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "chat_model": self.chat_model,
            "embed_model": self.embed_model,
            "ollama_base_url": self.ollama_base_url,
            "watched_roots": list(self.watched_roots),
            "watch_ignore_globs": list(self.watch_ignore_globs),
            "watch_debounce_seconds": self.watch_debounce_seconds,
        }


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
