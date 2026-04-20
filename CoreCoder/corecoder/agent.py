"""Core agent loop.

Skill system
------------
- Agent maintains a per-instance tool registry (_tool_registry).
- skill_search and tool_forge are always available as built-in tools.
- Skills are lazy-loaded on demand via skill_search.
- After each task completes, Agent scores whether the work is worth saving
  as a skill, and if so asks the user for confirmation before persisting.
"""

import concurrent.futures
from typing import Any
from .llm import LLM
from .tools import CORE_TOOLS
from .tools.base import Tool
from .tools.agent import AgentTool
from .tools.skill_search import SkillSearchTool
from .tools.tool_forge import ToolForgeTool
from .prompt import system_prompt
from .context import ContextManager


# Minimum score (0-10) to prompt the user about saving a skill
_SKILL_SAVE_THRESHOLD = 6


class Agent:
    def __init__(
        self,
        llm: LLM,
        tools: list[Tool] | None = None,
        max_context_tokens: int = 128_000,
        max_rounds: int = 50,
        on_confirm=None,
        on_skill_prompt=None,
        on_tool_retention_prompt=None,
    ):
        self.llm = llm
        self.max_rounds = max_rounds
        self.on_confirm = on_confirm        # (tool_name, args) -> bool
        self.on_skill_prompt = on_skill_prompt  # (name, desc, code) -> bool | None
        self.on_tool_retention_prompt = on_tool_retention_prompt  # (name, desc, code, source) -> str
        self.context = ContextManager(max_tokens=max_context_tokens)
        self.messages: list[dict] = []

        # Per-instance tool registry - keyed by name for O(1) lookup
        self._tool_registry: dict[str, Tool] = {}
        self._tool_meta: dict[str, dict[str, Any]] = {}
        self._task_seq = 0
        self._active_task_id: int | None = None

        base_tools = tools if tools is not None else list(CORE_TOOLS)

        # Create per-instance skill tools (need back-ref to this agent)
        skill_search = SkillSearchTool()
        tool_forge = ToolForgeTool()

        for t in [*base_tools, skill_search, tool_forge]:
            self._register(t)

        # Wire up agent back-references
        for t in self._tool_registry.values():
            if isinstance(t, AgentTool):
                t._parent_agent = self
            if isinstance(t, SkillSearchTool):
                t._agent = self
            if isinstance(t, ToolForgeTool):
                t._agent = self

        self._system = system_prompt(list(self._tool_registry.values()))

    # -- Tool registry ---------------------------------------------------------

    def _register(self, tool: Tool):
        self._tool_registry[tool.name] = tool

    def register_tool(
        self,
        tool: Tool,
        *,
        source: str = "dynamic",
        ephemeral: bool = False,
        code: str | None = None,
        description: str | None = None,
        task_id: int | None = None,
    ):
        """Hot-register a skill and rebuild system prompt so LLM sees it immediately."""
        self._register(tool)
        self._tool_meta[tool.name] = {
            "source": source,
            "ephemeral": ephemeral,
            "code": code,
            "description": description or getattr(tool, "description", ""),
            "task_id": task_id,
            "saved": False,
        }
        self._system = system_prompt(list(self._tool_registry.values()))

    @property
    def tools(self) -> list[Tool]:
        return list(self._tool_registry.values())

    def _get_tool(self, name: str) -> Tool | None:
        return self._tool_registry.get(name)

    def unregister_tool(self, name: str):
        """Remove a dynamically registered tool from the current agent."""
        if name in self._tool_registry:
            del self._tool_registry[name]
        self._tool_meta.pop(name, None)
        self._system = system_prompt(list(self._tool_registry.values()))

    def save_tool_to_library(self, name: str) -> bool:
        """Persist a dynamically forged tool to the skill library."""
        meta = self._tool_meta.get(name)
        if not meta:
            return False
        code = meta.get("code")
        desc = meta.get("description")
        if not code or not desc:
            return False

        from .skill_library import get_library
        lib = get_library()
        if not lib.save(name, desc, code):
            return False

        meta["saved"] = True
        meta["ephemeral"] = False
        meta["source"] = "skill"
        return True

    def retain_tool_for_session(self, name: str) -> bool:
        """Keep a forged tool available for the rest of the current process."""
        meta = self._tool_meta.get(name)
        if not meta:
            return False
        meta["ephemeral"] = False
        meta["source"] = "session"
        return True

    def _task_forged_tools(self, task_id: int) -> list[str]:
        return [
            name for name, meta in self._tool_meta.items()
            if meta.get("source") == "forged" and meta.get("task_id") == task_id
        ]

    def _cleanup_task_tools(self, task_id: int):
        """Drop ephemeral tools created for the finished task unless persisted."""
        for name in list(self._task_forged_tools(task_id)):
            meta = self._tool_meta.get(name, {})
            if meta.get("ephemeral", False) and not meta.get("saved", False):
                self.unregister_tool(name)

    # -- Message helpers -------------------------------------------------------

    def _full_messages(self) -> list[dict]:
        return [{"role": "system", "content": self._system}] + self.messages

    def _tool_schemas(self) -> list[dict]:
        return [t.schema() for t in self._tool_registry.values()]

    # -- Main chat loop --------------------------------------------------------

    def chat(self, user_input: str, on_token=None, on_tool=None) -> str:
        self._task_seq += 1
        task_id = self._task_seq
        self._active_task_id = task_id
        cleaned = False
        self.messages.append({"role": "user", "content": user_input})
        self.context.maybe_compress(self.messages, self.llm)

        # Track which tools were actually called this turn
        tools_called: list[str] = []

        try:
            for _ in range(self.max_rounds):
                resp = self.llm.chat(
                    messages=self._full_messages(),
                    tools=self._tool_schemas(),
                    on_token=on_token,
                )

                if not resp.tool_calls:
                    self.messages.append(resp.message)
                    final_response = resp.content

                    # After task completes: evaluate whether to save as skill
                    self._maybe_offer_skill(task_id, user_input, final_response, tools_called)
                    self._cleanup_task_tools(task_id)
                    self._active_task_id = None
                    cleaned = True

                    return final_response

                self.messages.append(resp.message)

                if len(resp.tool_calls) == 1:
                    tc = resp.tool_calls[0]
                    tools_called.append(tc.name)
                    if on_tool:
                        on_tool(tc.name, tc.arguments)
                    result = self._exec_tool(tc)
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })
                else:
                    results = self._exec_tools_parallel(resp.tool_calls, on_tool)
                    for tc, result in zip(resp.tool_calls, results):
                        tools_called.append(tc.name)
                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        })

                self.context.maybe_compress(self.messages, self.llm)

            self._cleanup_task_tools(task_id)
            self._active_task_id = None
            cleaned = True
            return "(reached maximum tool-call rounds)"
        finally:
            if not cleaned:
                self._cleanup_task_tools(task_id)
                self._active_task_id = None

    # -- Skill save offer ------------------------------------------------------

    def _maybe_offer_skill(
        self, task_id: int, user_input: str, response: str, tools_called: list[str]
    ):
        """After a task completes, score it and optionally offer to save as skill.

        Scoring criteria (hard rules, no LLM call needed):
          +3  used bash with non-trivial code (multi-step pipeline)
          +2  used write_file or edit_file (produced reusable artifact)
          +2  used 3+ different tools in one task
          +2  response contains a code block (generated reusable logic)
          +1  query contains reuse signals ('every time', 'always', 'script',
                'automate', 'batch', 'generate', 'parse', 'convert', 'analyze')
          -5  already used skill_search or tool_forge (skill already handled)
          -3  simple query (< 8 words and no code in response)

        If score >= threshold AND on_skill_prompt is set, ask the user.
        """
        # Offer to retain or persist any forged tools that were actually used in this task.
        used_forged = [
            name for name in self._task_forged_tools(task_id)
            if name in tools_called
        ]
        if used_forged:
            for name in used_forged:
                meta = self._tool_meta.get(name, {})
                code = meta.get("code")
                desc = meta.get("description", "")
                if not code:
                    continue
                action = "discard"
                if self.on_tool_retention_prompt is not None:
                    action = self.on_tool_retention_prompt(name, desc, code, "forged")
                if action == "skill":
                    self.save_tool_to_library(name)
                elif action == "session":
                    self.retain_tool_for_session(name)
            return

        used_session_tools = [
            name for name in set(tools_called)
            if self._tool_meta.get(name, {}).get("source") == "session"
        ]
        if used_session_tools:
            for name in used_session_tools:
                meta = self._tool_meta.get(name, {})
                code = meta.get("code")
                desc = meta.get("description", "")
                if not code or self.on_tool_retention_prompt is None:
                    continue
                action = self.on_tool_retention_prompt(name, desc, code, "session")
                if action == "skill":
                    self.save_tool_to_library(name)
                elif action == "discard":
                    self.unregister_tool(name)

        if self.on_skill_prompt is None:
            return

        # Don't offer generic skill extraction if a skill was already searched this turn.
        if "skill_search" in tools_called or "tool_forge" in tools_called:
            return

        score = 0

        # +3 bash with non-trivial content
        if "bash" in tools_called:
            score += 3

        # +2 produced file artifacts
        if "write_file" in tools_called or "edit_file" in tools_called:
            score += 2

        # +2 multi-tool task
        unique_tools = set(t for t in tools_called if t not in ("skill_search", "tool_forge"))
        if len(unique_tools) >= 3:
            score += 2

        # +2 response contains a code block
        if "```" in response:
            score += 2

        # +1 reuse signals in the query
        reuse_signals = {
            "every time", "always", "script", "automate", "batch",
            "generate", "parse", "convert", "analyze", "extract",
            "transform", "process", "report", "summarize",
        }
        query_lower = user_input.lower()
        if any(sig in query_lower for sig in reuse_signals):
            score += 1

        # -3 trivial query with no code
        if len(user_input.split()) < 8 and "```" not in response:
            score -= 3

        if score < _SKILL_SAVE_THRESHOLD:
            return

        # Ask LLM to suggest a name + description for the skill
        skill_meta = self._suggest_skill_meta(user_input, response)
        if not skill_meta:
            return

        name, desc, code = skill_meta

        # Ask the user (via callback set by CLI)
        save = self.on_skill_prompt(name, desc, code)
        if not save:
            return

        # Save to library
        from .skill_library import get_library
        lib = get_library()
        if lib.save(name, desc, code):
            # Hot-register so it's immediately usable in this session
            from .skill_library import _instantiate_tool
            tool = _instantiate_tool(code)
            if tool:
                self.register_tool(tool, source="skill")

    def _suggest_skill_meta(
        self, user_input: str, response: str
    ) -> tuple[str, str, str] | None:
        """Ask LLM to produce a skill name, description, and Tool class code."""
        # Gather the bash commands / code blocks from recent tool results
        recent_tool_results = []
        for msg in self.messages[-20:]:
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                if content and len(content) < 2000:
                    recent_tool_results.append(content)

        context_snippet = "\n---\n".join(recent_tool_results[-5:])

        prompt = f"""\
A user just completed this task:
  Query: {user_input}
  Final response summary: {response[:500]}
  Tool outputs (recent): {context_snippet[:1000]}

Your job: extract the reusable logic from this task and package it as a
CoreCoder Tool subclass that can be saved to the skill library.

Requirements:
1. Class must inherit from Tool: `from corecoder.tools.base import Tool`
2. Set name (snake_case), description, parameters (JSON Schema)
3. Implement execute(**kwargs) -> str, always return a string
4. Use only Python standard library
5. Handle errors gracefully

Return a JSON object with exactly these keys:
{{
  "name": "snake_case_tool_name",
  "description": "one sentence description",
  "code": "full python code for the Tool subclass"
}}
Return ONLY the JSON, no explanation.
"""
        try:
            resp = self.llm.chat(
                messages=[
                    {"role": "system", "content": "You output only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
            )
            import json, re
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

    # -- Tool execution --------------------------------------------------------

    def _exec_tool(self, tc) -> str:
        tool = self._get_tool(tc.name)
        if tool is None:
            return f"Error: unknown tool '{tc.name}'"
        if tool.requires_confirm and self.on_confirm:
            if not self.on_confirm(tc.name, tc.arguments):
                return f"User denied execution of {tc.name}."
        try:
            return tool.execute(**tc.arguments)
        except TypeError as e:
            return f"Error: bad arguments for {tc.name}: {e}"
        except Exception as e:
            return f"Error executing {tc.name}: {e}"

    def _exec_tools_parallel(self, tool_calls, on_tool=None) -> list[str]:
        denied: dict[int, str] = {}
        for i, tc in enumerate(tool_calls):
            if on_tool:
                on_tool(tc.name, tc.arguments)
            tool = self._get_tool(tc.name)
            if tool and tool.requires_confirm and self.on_confirm:
                if not self.on_confirm(tc.name, tc.arguments):
                    denied[i] = f"User denied execution of {tc.name}."

        approved = [(i, tc) for i, tc in enumerate(tool_calls) if i not in denied]
        results: dict[int, str] = dict(denied)

        if approved:
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                futures = {pool.submit(self._exec_tool_no_confirm, tc): i for i, tc in approved}
                for future in concurrent.futures.as_completed(futures):
                    results[futures[future]] = future.result()

        return [results[i] for i in range(len(tool_calls))]

    def _exec_tool_no_confirm(self, tc) -> str:
        tool = self._get_tool(tc.name)
        if tool is None:
            return f"Error: unknown tool '{tc.name}'"
        try:
            return tool.execute(**tc.arguments)
        except TypeError as e:
            return f"Error: bad arguments for {tc.name}: {e}"
        except Exception as e:
            return f"Error executing {tc.name}: {e}"

    def reset(self):
        self.messages.clear()
        for name, meta in list(self._tool_meta.items()):
            if meta.get("ephemeral", False):
                self.unregister_tool(name)
        self._active_task_id = None
