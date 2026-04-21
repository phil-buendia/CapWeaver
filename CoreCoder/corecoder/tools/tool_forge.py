"""ToolForgeTool - let the agent create new tools on demand.

Workflow:
  1. Agent decides a task needs a reusable tool
  2. Agent calls tool_search / skill_search first - if nothing matches, calls tool_forge
  3. tool_forge asks the LLM to generate a Tool subclass
  4. Validates the code (syntax + instantiation)
  5. Hot-registers into the running agent as an ephemeral tool
  6. Task finishes, then the user can choose whether to discard it, keep it
     in-session, retain it as a persistent tool, and optionally package a skill
"""

import re
from .base import Tool

# -- Source snippets embedded in the generation prompt -----------------------

_TOOL_BASE_SOURCE = """\
class Tool(ABC):
    name: str
    description: str
    parameters: dict  # JSON Schema
    requires_confirm: bool = False

    @abstractmethod
    def execute(self, **kwargs) -> str: ...
"""

_EXAMPLE_TOOL = """\
from corecoder.tools.base import Tool

class WordCountTool(Tool):
    name = "word_count"
    description = "Count words in a text string."
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Input text"},
        },
        "required": ["text"],
    }

    def execute(self, text: str) -> str:
        count = len(text.split())
        return f"Word count: {count}"
"""


class ToolForgeTool(Tool):
    name = "tool_forge"
    description = (
        "Generate a new reusable tool on demand. "
        "Call tool_search and/or skill_search FIRST. Only call this when no existing "
        "retained tool or skill matches. "
        "The generated tool is registered for the current task immediately. "
        "After the task, the user can decide whether to discard it, keep it in the "
        "session, retain it as a persistent tool, or further package it as a skill."
    )
    parameters = {
        "type": "object",
        "properties": {
            "tool_name": {
                "type": "string",
                "description": "Snake_case name for the new tool, e.g. 'csv_column_stats'",
            },
            "description": {
                "type": "string",
                "description": "Clear description of what the tool does and its inputs/outputs",
            },
            "task_context": {
                "type": "string",
                "description": "The current task context to help generate the right implementation",
            },
        },
        "required": ["tool_name", "description", "task_context"],
    }

    def __init__(self):
        # Per-instance agent reference, set by Agent.__init__
        self._agent = None

    def execute(self, tool_name: str, description: str, task_context: str) -> str:
        if self._agent is None:
            return "Error: tool_forge not initialized (no agent reference)."

        from ..skill_library import get_library
        lib = get_library()

        # If skill already exists, just load it
        if lib.exists(tool_name):
            if not any(t.name == tool_name for t in self._agent.tools):
                tool = lib.load(tool_name)
                if tool:
                    self._agent.register_tool(tool, source="skill")
            return f"Skill '{tool_name}' already exists and is now loaded. Proceed to use it."

        # Generate with auto-retry on validation failure (up to 3 attempts)
        last_error = ""
        code = ""
        for attempt in range(3):
            code = self._generate_code(tool_name, description, task_context, last_error)
            if not code:
                return "Error: LLM did not return usable code."

            ok, error, instance = _validate(code)
            if ok:
                break
            last_error = f"Attempt {attempt+1} failed: {error}\nCode was:\n{code}"
        else:
            return (
                f"Tool generation failed after 3 attempts. Last error: {error}\n"
                f"Last generated code:\n```python\n{code}\n```"
            )

        # Hot-register into the running agent as an ephemeral tool.
        # The agent may later persist it if the user explicitly confirms.
        self._agent.register_tool(
            instance,
            source="forged",
            retention="ephemeral",
            ephemeral=True,
            code=code,
            description=description,
            task_id=self._agent._active_task_id,
        )
        self._agent.telemetry.log(
            "tool_forged",
            task_id=self._agent._active_task_id,
            tool_name=tool_name,
            description=description,
        )

        return (
            f"Tool '{tool_name}' created, validated, and registered for this task. "
            f"It is available immediately. If it proves useful, the user can choose "
            f"to save it as a skill after the task completes."
        )

    def _generate_code(
        self, tool_name: str, description: str, task_context: str, last_error: str = ""
    ) -> str:
        """Ask the LLM to write the Tool subclass."""
        retry_section = ""
        if last_error:
            retry_section = f"\n## Previous Attempt Failed\n{last_error}\nFix the issues above.\n"

        prompt = f"""\
You are a Tool Maker for the CoreCoder agent framework.
Generate a Python Tool subclass for the following capability.

## Tool Base Class
```python
{_TOOL_BASE_SOURCE}```

## Example Tool
```python
{_EXAMPLE_TOOL}```

## Your Task
Tool name: {tool_name}
Description: {description}
Current task context: {task_context}
{retry_section}
## Requirements
1. Class MUST inherit from Tool: `from corecoder.tools.base import Tool`
2. Set class attributes: name="{tool_name}", description (str), parameters (JSON Schema dict)
3. parameters must have: {{"type": "object", "properties": {{...}}, "required": [...]}}
4. Implement execute(**kwargs) -> str -- ALWAYS return a string, never raise
5. Use ONLY Python standard library (no pip installs)
6. Handle all errors gracefully, return error message strings
7. Keep it under 80 lines

Return ONLY the Python code inside a ```python``` block. No explanation.
"""
        try:
            resp = self._agent.llm.chat(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a precise code generator. Output only code, no explanations.",
                    },
                    {"role": "user", "content": prompt},
                ],
            )
            return _extract_code(resp.content)
        except Exception:
            return ""


# -- Helpers ------------------------------------------------------------------

def _extract_code(text: str) -> str:
    """Pull the first ```python ... ``` block from LLM output."""
    m = re.search(r"```python\s*(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # fallback: strip any ``` markers
    text = re.sub(r"```\w*", "", text).strip()
    return text


def _validate(code: str):
    """
    Validate generated tool code.
    Returns (ok: bool, error: str, instance: Tool | None)
    """
    import ast as _ast

    # 1. Syntax check
    try:
        _ast.parse(code)
    except SyntaxError as e:
        return False, f"SyntaxError: {e}", None

    # 2. Instantiation check
    try:
        from .base import Tool as _Tool
        namespace: dict = {}
        exec("from corecoder.tools.base import Tool", namespace)
        exec(code, namespace)

        instance = None
        for obj in namespace.values():
            if (
                isinstance(obj, type)
                and issubclass(obj, _Tool)
                and obj is not _Tool
            ):
                instance = obj()
                break

        if instance is None:
            return False, "No Tool subclass found in generated code.", None

        # 3. Schema check
        schema = instance.schema()
        required_keys = {"type", "function"}
        if not required_keys.issubset(schema.keys()):
            return False, f"Schema missing keys: {required_keys - schema.keys()}", None

        return True, "", instance

    except Exception as e:
        return False, f"Runtime error: {e}", None
