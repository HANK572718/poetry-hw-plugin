"""Persistent local state: last successfully installed variant."""

from __future__ import annotations

import json
from pathlib import Path

_STATE_FILE = ".hw-plugin-state"


def read_last_variant(root: Path) -> str | None:
    """Return the last successfully installed variant name, or None."""
    state_file = root / _STATE_FILE
    if not state_file.exists():
        return None
    try:
        return json.loads(state_file.read_text(encoding="utf-8")).get("last_variant")
    except Exception:
        return None


def write_last_variant(root: Path, variant: str) -> None:
    """Persist the last successfully installed variant name."""
    try:
        (root / _STATE_FILE).write_text(
            json.dumps({"last_variant": variant}, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
