"""Native folder picker helpers (macOS)."""

from __future__ import annotations

import subprocess
from pathlib import Path


def pick_folder_macos() -> str:
    """
    Open native macOS folder chooser via AppleScript and return POSIX path.
    Raises RuntimeError on cancel/failure.
    """
    script = 'POSIX path of (choose folder with prompt "Select a folder for MemoryAgent to watch")'
    try:
        out = subprocess.check_output(
            ["osascript", "-e", script],
            stderr=subprocess.STDOUT,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        msg = (e.output or "").strip()
        if "User canceled" in msg or "User cancelled" in msg:
            raise RuntimeError("Folder selection was cancelled.") from e
        raise RuntimeError(f"Folder picker failed: {msg or e}") from e
    p = out.strip()
    if not p:
        raise RuntimeError("Folder picker returned no path.")
    rp = Path(p).expanduser().resolve()
    if not rp.is_dir():
        raise RuntimeError(f"Selected path is not a directory: {rp}")
    return str(rp)
