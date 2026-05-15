# -*- coding: utf-8 -*-
"""Persistent goal support for long-running agent work."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from .storage import corecoder_home


@dataclass
class Goal:
    text: str
    updated_at: str


class GoalManager:
    def __init__(self, path: Path | None = None):
        self.path = path or (corecoder_home() / "goal.json")

    def get(self) -> Goal | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            text = str(data.get("text", "")).strip()
            if not text:
                return None
            return Goal(text=text, updated_at=data.get("updated_at", ""))
        except Exception:
            return None

    def set(self, text: str) -> Goal:
        goal = Goal(text=text.strip(), updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(goal.__dict__, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return goal

    def clear(self):
        if self.path.exists():
            self.path.unlink()
