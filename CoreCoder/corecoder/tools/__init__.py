"""Tool registry.

CORE_TOOLS: the minimal built-in tools every Agent starts with.
skill_search and tool_forge are NOT listed here - Agent injects them
as per-instance objects so they can hold a back-reference to the agent.
"""

from .bash import BashTool
from .read import ReadFileTool
from .write import WriteFileTool
from .edit import EditFileTool
from .glob_tool import GlobTool
from .grep import GrepTool
from .agent import AgentTool

# Core tools shared across agents (stateless, no agent back-reference needed)
CORE_TOOLS = [
    BashTool(),
    ReadFileTool(),
    WriteFileTool(),
    EditFileTool(),
    GlobTool(),
    GrepTool(),
    AgentTool(),
]

# Legacy alias so old imports don't break immediately
ALL_TOOLS = CORE_TOOLS


def get_tool(name: str):
    """Look up a tool by name in CORE_TOOLS (legacy helper)."""
    for t in CORE_TOOLS:
        if t.name == name:
            return t
    return None
