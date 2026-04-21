"""Skillification policy + metadata generation helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class SkillificationSuggestion:
    recommendation: str
    score: int
    reasons: list[str]


class SkillificationEngine:
    def __init__(self, llm):
        self.llm = llm

    def suggest_from_retained_tool(self, tool_name: str, tool_desc: str) -> SkillificationSuggestion:
        score = 2
        reasons = ["retained tool already proved worth keeping"]
        if any(token in tool_desc.lower() for token in ("workflow", "pipeline", "analyze", "extract", "convert", "report")):
            score += 2
            reasons.append("tool description implies a reusable business flow")
        if score >= 3:
            return SkillificationSuggestion("skillify", score, reasons)
        return SkillificationSuggestion("skip", score, reasons)

    def suggest_workflow_skill(
        self,
        *,
        user_input: str,
        response: str,
        tools_called: list[str],
    ) -> SkillificationSuggestion:
        score = 0
        reasons: list[str] = []
        query_lower = user_input.lower()

        if any(token in query_lower for token in ("workflow", "pipeline", "review", "process", "analyze", "report", "template", "again", "repeat")):
            score += 3
            reasons.append("task reads like a reusable business workflow")
        if len(set(tools_called)) >= 3:
            score += 2
            reasons.append("workflow uses several coordinated tools")
        if "```" in response:
            score += 1
            reasons.append("response includes reusable logic")

        if score >= 4:
            return SkillificationSuggestion("skillify", score, reasons or ["workflow looks reusable"])
        return SkillificationSuggestion("skip", score, reasons or ["not enough workflow signal"])

    def build_skill_from_retained_tool(
        self, tool_name: str, tool_desc: str, tool_code: str
    ) -> tuple[str, str, str] | None:
        prompt = f"""\
You are packaging a retained tool into a higher-level skill for CoreCoder.

Retained tool name: {tool_name}
Retained tool description: {tool_desc}

The skill should be conceptually broader than the raw tool. A skill may simply
delegate to the retained tool, but it should be named and described as a
workflow-facing reusable capability.

Retained tool code:
```python
{tool_code}
```

Return a JSON object with exactly these keys:
{{
  "name": "snake_case_skill_name",
  "description": "one sentence workflow-level skill description",
  "code": "full python code for a Tool subclass that loads the retained tool from corecoder.tool_library and delegates to it"
}}

Rules for the generated skill code:
1. Inherit from Tool
2. Use only Python standard library plus project imports
3. Load the retained tool from corecoder.tool_library by name: "{tool_name}"
4. Return strings only
5. Keep it concise and robust

Return ONLY the JSON, no explanation.
"""
        return self._run_skill_json_prompt(prompt)

    def build_skill_from_workflow(
        self, user_input: str, response: str, recent_tool_results: list[str]
    ) -> tuple[str, str, str] | None:
        context_snippet = "\n---\n".join(recent_tool_results[-5:])
        prompt = f"""\
A user just completed this task:
  Query: {user_input}
  Final response summary: {response[:500]}
  Tool outputs (recent): {context_snippet[:1000]}

Your job: extract the reusable workflow from this task and package it as a
CoreCoder Tool subclass that can be saved to the skill library.

Important:
- This skill does NOT need to come from a newly forged tool.
- It may wrap or orchestrate existing built-in tools, retained tools, or pure
  Python logic.
- Focus on the reusable business workflow, not just the low-level tool.

Requirements:
1. Class must inherit from Tool: `from corecoder.tools.base import Tool`
2. Set name (snake_case), description, parameters (JSON Schema)
3. Implement execute(**kwargs) -> str, always return a string
4. Use only Python standard library
5. Handle errors gracefully

Return a JSON object with exactly these keys:
{{
  "name": "snake_case_skill_name",
  "description": "one sentence workflow-level description",
  "code": "full python code for the Tool subclass"
}}
Return ONLY the JSON, no explanation.
"""
        return self._run_skill_json_prompt(prompt)

    def _run_skill_json_prompt(self, prompt: str) -> tuple[str, str, str] | None:
        try:
            resp = self.llm.chat(
                messages=[
                    {"role": "system", "content": "You output only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
            )
            text = resp.content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            data = json.loads(text)
            name = data.get("name", "").strip()
            desc = data.get("description", "").strip()
            code = data.get("code", "").strip()
            if name and desc and code:
                return name, desc, code
        except Exception:
            pass
        return None
