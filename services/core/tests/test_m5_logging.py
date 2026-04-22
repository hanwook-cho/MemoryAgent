"""M5: logging rotation and bounded growth behavior."""

from __future__ import annotations

import logging
from pathlib import Path

from memoryagent.logging_setup import configure_logging


def test_rotating_file_handler_rolls_logs(
    data_dir: Path, monkeypatch
) -> None:
    # Force tiny log files so rollover happens quickly.
    monkeypatch.setenv("MEMORYAGENT_LOG_MAX_BYTES", "800")
    monkeypatch.setenv("MEMORYAGENT_LOG_BACKUP_COUNT", "2")

    configure_logging(data_dir, force=True)
    lg = logging.getLogger("memoryagent.test_rotation")
    payload = "x" * 200
    for i in range(80):
        lg.info("rotation_test idx=%s payload=%s", i, payload)

    for h in logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:
            pass

    logs_dir = data_dir / "logs"
    core = logs_dir / "core.log"
    rotated = sorted(logs_dir.glob("core.log.*"))
    assert core.is_file()
    # At least one rollover file should exist.
    assert len(rotated) >= 1
