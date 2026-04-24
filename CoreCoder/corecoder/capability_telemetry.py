# -*- coding: utf-8 -*-
"""Capability telemetry for growth / retention / skillification events."""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any


EVENTS_DIR = Path(os.getenv("CORECODER_HOME", Path.home() / ".corecoder"))
EVENTS_FILE = EVENTS_DIR / "capability_events.jsonl"


class CapabilityTelemetry:
    def __init__(self, file_path: Path | None = None):
        self.file_path = file_path or EVENTS_FILE
        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            self.file_path = Path.cwd() / ".corecoder" / "capability_events.jsonl"
            self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event_type: str, **payload: Any):
        event = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event_type": event_type,
            **payload,
        }
        try:
            with self.file_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except PermissionError:
            self.file_path = Path.cwd() / ".corecoder" / "capability_events.jsonl"
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            with self.file_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def summary(self) -> dict[str, Any]:
        if not self.file_path.exists():
            return {
                "total_events": 0,
                "tasks": 0,
                "forges": 0,
                "retained_tools": 0,
                "session_kept": 0,
                "discarded_tools": 0,
                "skills_saved": 0,
                "workflow_skills_saved": 0,
                "retained_tool_skills_saved": 0,
                "skill_revisions": 0,
            }

        counters = Counter()
        retained_names: set[str] = set()
        skill_names: set[str] = set()

        with self.file_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                counters["total_events"] += 1
                event_type = event.get("event_type", "")
                counters[event_type] += 1
                if event_type == "tool_retained" and event.get("tool_name"):
                    retained_names.add(event["tool_name"])
                if event_type == "skill_saved" and event.get("skill_name"):
                    skill_names.add(event["skill_name"])
                source = event.get("skill_source")
                if event_type == "skill_saved" and source == "workflow":
                    counters["workflow_skills_saved"] += 1
                if event_type == "skill_saved" and source == "retained_tool":
                    counters["retained_tool_skills_saved"] += 1

        return {
            "total_events": counters["total_events"],
            "tasks": counters["task_completed"],
            "forges": counters["tool_forged"],
            "retained_tools": len(retained_names),
            "session_kept": counters["tool_session_kept"],
            "discarded_tools": counters["tool_discarded"],
            "skills_saved": len(skill_names),
            "workflow_skills_saved": counters["workflow_skills_saved"],
            "retained_tool_skills_saved": counters["retained_tool_skills_saved"],
            "skill_revisions": counters["skill_revised"],
        }


_telemetry: CapabilityTelemetry | None = None


def get_telemetry() -> CapabilityTelemetry:
    global _telemetry
    if _telemetry is None:
        _telemetry = CapabilityTelemetry()
    return _telemetry
