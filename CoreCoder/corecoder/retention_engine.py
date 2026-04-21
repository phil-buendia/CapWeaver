"""Retention policy engine for capability lifecycle decisions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RetentionSuggestion:
    recommendation: str
    score: int
    reasons: list[str]


class RetentionEngine:
    """Rule-based retention suggestions for tools and workflows."""

    _REUSE_SIGNALS = {
        "every time", "always", "repeat", "reusable", "workflow", "pipeline",
        "template", "again", "batch", "automate", "often", "frequently",
    }
    _STRUCTURED_SIGNALS = {
        "json", "csv", "xml", "log", "parse", "analyze", "transform",
        "extract", "convert", "report", "summarize", "validate",
    }

    def suggest_tool_retention(
        self,
        *,
        user_input: str,
        tool_name: str,
        description: str,
        source: str,
        tools_called: list[str],
    ) -> RetentionSuggestion:
        score = 0
        reasons: list[str] = []
        query_lower = user_input.lower()
        desc_lower = description.lower()

        if any(token in query_lower for token in self._REUSE_SIGNALS):
            score += 3
            reasons.append("user signaled repeated reuse")

        if any(token in query_lower or token in desc_lower for token in self._STRUCTURED_SIGNALS):
            score += 2
            reasons.append("tool solves a structured reusable task")

        unique_tools = set(tools_called)
        if len(unique_tools) >= 3:
            score += 1
            reasons.append("appeared in a multi-step task")

        if source == "session":
            score += 1
            reasons.append("already survived one task as a session tool")

        if len(user_input.split()) < 8:
            score -= 1
            reasons.append("task looks short and possibly one-off")

        if any(marker in query_lower for marker in ("c:\\", "d:\\", "./", "../")):
            score -= 1
            reasons.append("request looks path-specific")

        if score >= 4:
            return RetentionSuggestion("retain", score, reasons or ["high reuse potential"])
        if score >= 1:
            return RetentionSuggestion("session", score, reasons or ["may be useful within this run"])
        return RetentionSuggestion("discard", score, reasons or ["looks too specific or low reuse"])

    def suggest_workflow_skill(
        self,
        *,
        user_input: str,
        response: str,
        tools_called: list[str],
        skill_already_used: bool,
    ) -> RetentionSuggestion:
        score = 0
        reasons: list[str] = []
        query_lower = user_input.lower()

        if skill_already_used:
            return RetentionSuggestion("skip", -99, ["already reused an existing skill"])

        if any(token in query_lower for token in self._REUSE_SIGNALS):
            score += 3
            reasons.append("user described a reusable workflow")

        if len(set(t for t in tools_called if t not in ("tool_search", "skill_search", "tool_forge"))) >= 3:
            score += 2
            reasons.append("workflow spans multiple tools")

        if "```" in response:
            score += 1
            reasons.append("response contains reusable logic or code")

        if any(token in query_lower for token in self._STRUCTURED_SIGNALS):
            score += 1
            reasons.append("task belongs to a repeatable processing pattern")

        if len(user_input.split()) < 8 and "```" not in response:
            score -= 2
            reasons.append("request looks too small for a standalone skill")

        if score >= 4:
            return RetentionSuggestion("save_skill", score, reasons or ["workflow looks reusable"])
        return RetentionSuggestion("skip", score, reasons or ["workflow reuse value is still low"])
