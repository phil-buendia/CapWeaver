# -*- coding: utf-8 -*-
"""Task trajectory recording for capability evolution.

Telemetry answers "what happened in aggregate"; trajectories preserve the
step-by-step evidence needed to later create or improve reusable skills.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


DEFAULT_CORECODER_HOME = Path(os.getenv("CORECODER_HOME", Path.home() / ".corecoder"))
TRAJECTORY_DIR = DEFAULT_CORECODER_HOME / "trajectories"


class TrajectoryRecorder:
    """Append-only JSONL recorder for a single task run."""

    def __init__(self, task_id: int, *, base_dir: Path | None = None):
        self.task_id = task_id
        self.base_dir = base_dir or TRAJECTORY_DIR
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            self.base_dir = Path.cwd() / ".corecoder" / "trajectories"
            self.base_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.path = self.base_dir / f"task_{stamp}_{task_id}.jsonl"
        self._closed = False

    def record(self, event_type: str, **payload: Any):
        if self._closed:
            return
        event = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "task_id": self.task_id,
            "event_type": event_type,
            **payload,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def close(self, status: str = "completed"):
        if self._closed:
            return
        self.record("trajectory_closed", status=status)
        self._closed = True


def list_trajectories(limit: int = 10) -> list[dict[str, Any]]:
    """Return recent trajectory files with basic metadata."""
    directory = TRAJECTORY_DIR
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        directory = Path.cwd() / ".corecoder" / "trajectories"
        directory.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        items.append(
            {
                "path": str(path),
                "name": path.name,
                "size": path.stat().st_size,
                "modified": time.strftime(
                    "%Y-%m-%dT%H:%M:%S",
                    time.localtime(path.stat().st_mtime),
                ),
            }
        )
    return items
