# -*- coding: utf-8 -*-
"""Shared local storage helpers for CapWeaver runtime state."""

from __future__ import annotations

import os
from pathlib import Path


def corecoder_home() -> Path:
    """Return a writable runtime directory.

    Prefer CORECODER_HOME or the user's home directory. In locked-down
    environments, fall back to the current project process directory.
    """
    preferred = Path(os.getenv("CORECODER_HOME", Path.home() / ".corecoder"))
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        probe = preferred / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return preferred
    except (PermissionError, OSError):
        fallback = Path.cwd() / ".corecoder"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
