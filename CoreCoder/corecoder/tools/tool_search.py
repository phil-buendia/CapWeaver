"""ToolSearchTool - search the retained tool library and lazy-load matches.

Retained tools are executable building blocks saved in tool_store/. They are
separate from skills: a retained tool can be reused directly without implying
that the full workflow should be packaged as a skill.
"""

from .base import Tool


class ToolSearchTool(Tool):
    name = "tool_search"
    description = (
        "Search the retained tool library for reusable building-block tools that "
        "match the current task. Call this before tool_forge when you need a "
        "concrete executable tool rather than a higher-level skill."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Natural-language description of the tool capability you need, "
                    "e.g. 'analyze JSON structure and summarize nested fields'"
                ),
            }
        },
        "required": ["query"],
    }

    def __init__(self):
        self._agent = None

    def execute(self, query: str) -> str:
        from ..tool_library import get_tool_library

        lib = get_tool_library()
        candidates = lib.search(query, top_k=10)

        if candidates and self._agent is not None:
            matches = lib.semantic_search(query, candidates, self._agent.llm, top_k=3)
        else:
            matches = candidates[:3]

        if not matches:
            return (
                "No matching retained tools found.\n"
                "If you need a reusable low-level capability, consider skill_search next "
                "for workflow-level reuse, or tool_forge to build a new tool."
            )

        lines = ["Found matching retained tools:"]
        for meta in matches:
            tool_name = meta["name"]
            desc = meta.get("description", "")[:100]
            use_count = meta.get("use_count", 0)

            if self._agent is not None and any(t.name == tool_name for t in self._agent.tools):
                lines.append(f"  [loaded] {tool_name}: {desc}  (used {use_count}x)")
                continue

            if self._agent is not None:
                tool = lib.load(tool_name)
                code = lib.load_code(tool_name)
                if tool:
                    self._agent.register_tool(
                        tool,
                        source="retained_library",
                        retention="retained",
                        code=code,
                        description=desc,
                    )
                    lib.increment_use(tool_name)
                    lines.append(f"  [loaded] {tool_name}: {desc}  (used {use_count + 1}x)")
                else:
                    lines.append(f"  [failed] {tool_name}: {desc}")
            else:
                lines.append(f"  - {tool_name}: {desc}  (use_count={use_count})")

        lines.append(
            "\nLoaded retained tools are now registered as tools -- use them directly."
        )
        return "\n".join(lines)
