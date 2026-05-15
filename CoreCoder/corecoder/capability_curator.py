# -*- coding: utf-8 -*-
"""Offline capability curation for tools and skills.

The curator is intentionally conservative: it scores the library, writes a
report, and can archive explicitly requested items. It does not silently delete
or rewrite capabilities.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .capability_telemetry import get_telemetry
from .skill_library import get_library
from .storage import corecoder_home
from .tool_library import get_tool_library


@dataclass
class CuratorItem:
    kind: str
    name: str
    score: int
    recommendation: str
    reasons: list[str]
    metadata: dict[str, Any]


class CapabilityCurator:
    """Rubric-based capability library reviewer."""

    def __init__(self, report_dir: Path | None = None):
        self.report_dir = report_dir or (corecoder_home() / "curator")
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def review(self) -> tuple[list[CuratorItem], Path]:
        skills = [self._score_skill(item) for item in get_library().list_all()]
        tools = [self._score_tool(item) for item in get_tool_library().list_all()]
        items = sorted(skills + tools, key=lambda item: (item.recommendation, -item.score, item.name))
        report_path = self._write_report(items)
        get_telemetry().log(
            "curator_run",
            report_path=str(report_path),
            total_items=len(items),
            archive_candidates=sum(1 for item in items if item.recommendation == "archive_candidate"),
            improve_candidates=sum(1 for item in items if item.recommendation == "improve_candidate"),
        )
        return items, report_path

    def _score_skill(self, meta: dict[str, Any]) -> CuratorItem:
        score = 0
        reasons: list[str] = []
        use_count = int(meta.get("use_count", 0) or 0)
        revision_count = int(meta.get("revision_count", 0) or 0)

        if use_count >= 3:
            score += 4
            reasons.append("used repeatedly")
        elif use_count == 0:
            score -= 2
            reasons.append("never used")

        if revision_count > 0:
            score += 2
            reasons.append("has trajectory-derived revisions")

        skill_dir = Path(get_library().dir) / meta.get("dir", meta.get("name", ""))
        if not (skill_dir / "SKILL.md").exists():
            score -= 2
            reasons.append("missing SKILL.md procedural memory")
        if not (skill_dir / "skill.py").exists():
            score -= 4
            reasons.append("missing executable skill.py")

        recommendation = "keep"
        if score <= -2:
            recommendation = "archive_candidate"
        elif "missing SKILL.md procedural memory" in reasons or revision_count >= 2:
            recommendation = "improve_candidate"

        return CuratorItem("skill", meta["name"], score, recommendation, reasons or ["healthy"], meta)

    def _score_tool(self, meta: dict[str, Any]) -> CuratorItem:
        score = 0
        reasons: list[str] = []
        use_count = int(meta.get("use_count", 0) or 0)

        if use_count >= 3:
            score += 4
            reasons.append("used repeatedly")
        elif use_count == 0:
            score -= 1
            reasons.append("not reused yet")

        desc = meta.get("description", "").lower()
        if any(token in desc for token in ("workflow", "pipeline", "report", "analyze", "convert")):
            score += 2
            reasons.append("description suggests reusable workflow")

        tool_dir = Path(get_tool_library().dir) / meta.get("dir", meta.get("name", ""))
        if not (tool_dir / "tool.py").exists():
            score -= 4
            reasons.append("missing executable tool.py")

        recommendation = "keep"
        if score <= -3:
            recommendation = "archive_candidate"
        elif score >= 5:
            recommendation = "skillify_candidate"

        return CuratorItem("tool", meta["name"], score, recommendation, reasons or ["healthy"], meta)

    def _write_report(self, items: list[CuratorItem]) -> Path:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        path = self.report_dir / f"curator_{stamp}.md"
        lines = [
            "# CapWeaver Curator Report",
            "",
            f"Generated at: {time.strftime('%Y-%m-%dT%H:%M:%S')}",
            "",
            "| Kind | Name | Score | Recommendation | Reasons |",
            "|---|---|---:|---|---|",
        ]
        for item in items:
            reasons = "; ".join(item.reasons)
            lines.append(
                f"| {item.kind} | `{item.name}` | {item.score} | "
                f"`{item.recommendation}` | {reasons} |"
            )
        lines.extend(
            [
                "",
                "## Rubric",
                "",
                "- Repeated use increases confidence.",
                "- Missing executable files are archive candidates.",
                "- Missing `SKILL.md` makes a skill an improvement candidate.",
                "- Tool descriptions that look workflow-level may be skillification candidates.",
                "- The curator reports and suggests; it does not silently delete capabilities.",
            ]
        )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path


def archive_capability(kind: str, name: str) -> bool:
    if kind == "skill":
        return get_library().archive(name)
    if kind == "tool":
        return get_tool_library().archive(name)
    return False
