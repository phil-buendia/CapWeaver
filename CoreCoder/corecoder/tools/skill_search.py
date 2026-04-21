"""SkillSearchTool - search the skill library and lazy-load matching tools.

Search strategy (two-stage):
  1. Keyword overlap (fast, no LLM call) -- filters candidates
  2. LLM semantic re-ranking -- picks the truly relevant ones

The agent calls this when it decides a task might benefit from a reusable skill.
Matched skills are hot-registered into the running agent -- no restart needed.
"""

from .base import Tool


class SkillSearchTool(Tool):
    name = "skill_search"
    description = (
        "Search the skill library for existing reusable tools that match a task. "
        "Call this BEFORE using tool_forge, to check if a suitable skill already "
        "exists. Matching skills are automatically loaded and immediately available."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Natural-language description of the capability you need, "
                    "e.g. 'parse CSV and compute column statistics'"
                ),
            },
        },
        "required": ["query"],
    }

    def __init__(self):
        # Per-instance agent reference (set by Agent.__init__)
        self._agent = None

    def execute(self, query: str) -> str:
        from ..skill_library import get_library

        lib = get_library()

        # Stage 1: fast keyword search (no LLM)
        candidates = lib.search(query, top_k=10)

        # Stage 2: LLM semantic re-ranking (only if we have an agent + candidates)
        if candidates and self._agent is not None:
            matches = lib.semantic_search(
                query, candidates, self._agent.llm, top_k=3
            )
        else:
            matches = candidates[:3]

        if not matches:
            return (
                "No matching skills found in the library.\n"
                "Consider using tool_forge to create a new reusable skill."
            )

        lines = ["Found matching skills:"]
        for m in matches:
            skill_name = m["name"]
            desc = m.get("description", "")[:100]
            use_count = m.get("use_count", 0)

            # skip if already loaded in this session
            if self._agent is not None and any(
                t.name == skill_name for t in self._agent.tools
            ):
                lines.append(
                    f"  [loaded] {skill_name}: {desc}  (used {use_count}x)"
                )
                continue

            # lazy-load into the running agent
            if self._agent is not None:
                tool = lib.load(skill_name)
                if tool:
                    self._agent.register_tool(
                        tool,
                        source="skill_library",
                        retention="skill",
                        description=desc,
                    )
                    lib.increment_use(skill_name)
                    lines.append(
                        f"  [loaded] {skill_name}: {desc}  (used {use_count + 1}x)"
                    )
                else:
                    lines.append(f"  [failed] {skill_name}: {desc}")
            else:
                lines.append(f"  - {skill_name}: {desc}  (use_count={use_count})")

        lines.append(
            "\nLoaded skills are now registered as tools -- use them directly."
        )
        return "\n".join(lines)
