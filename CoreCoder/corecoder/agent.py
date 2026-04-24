"""Core agent loop.

Skill system
------------
- Agent maintains a per-instance tool registry (_tool_registry).
- Retained tools and skills are separate persistence layers.
- tool_search retrieves retained tools from tool_store/.
- skill_search and tool_forge are always available as built-in tools.
- Skills are lazy-loaded on demand via skill_search.
- After each task completes, Agent first decides what to do with the tool
  itself (discard / session / retain), then skillification can happen from
  either:
  1. a retained tool
  2. a reusable workflow even when no new tool was created
"""

import concurrent.futures
from typing import Any
from .capability_telemetry import get_telemetry
from .retention_engine import RetentionEngine
from .skillification_engine import SkillificationEngine
from .trajectory_recorder import TrajectoryRecorder
from .llm import LLM
from .tools import CORE_TOOLS
from .tools.base import Tool
from .tools.agent import AgentTool
from .tools.tool_search import ToolSearchTool
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
        on_skillification_prompt=None,
        on_skill_revision_prompt=None,
    ):
        self.llm = llm
        self.max_rounds = max_rounds
        self.on_confirm = on_confirm        # (tool_name, args) -> bool
        self.on_skill_prompt = on_skill_prompt  # (name, desc, code) -> bool | None
        self.on_tool_retention_prompt = on_tool_retention_prompt  # (name, desc, code, source) -> str
        self.on_skillification_prompt = on_skillification_prompt  # (tool_name, skill_name, desc, code) -> bool
        self.on_skill_revision_prompt = on_skill_revision_prompt  # (skill_name, note, reasons) -> bool
        self.context = ContextManager(max_tokens=max_context_tokens)
        self.messages: list[dict] = []
        self.telemetry = get_telemetry()
        self.retention_engine = RetentionEngine()
        self.skillification_engine = SkillificationEngine(llm)

        # Per-instance tool registry - keyed by name for O(1) lookup
        self._tool_registry: dict[str, Tool] = {}
        self._tool_meta: dict[str, dict[str, Any]] = {}
        self._task_seq = 0
        self._active_task_id: int | None = None

        base_tools = tools if tools is not None else list(CORE_TOOLS)

        # Create per-instance skill tools (need back-ref to this agent)
        tool_search = ToolSearchTool()
        skill_search = SkillSearchTool()
        tool_forge = ToolForgeTool()

        for t in [*base_tools, tool_search, skill_search, tool_forge]:
            self._register(t)

        # Wire up agent back-references
        for t in self._tool_registry.values():
            if isinstance(t, AgentTool):
                t._parent_agent = self
            if isinstance(t, ToolSearchTool):
                t._agent = self
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
        retention: str = "session",
        ephemeral: bool = False,
        code: str | None = None,
        description: str | None = None,
        task_id: int | None = None,
    ):
        """Hot-register a skill and rebuild system prompt so LLM sees it immediately."""
        self._register(tool)
        self._tool_meta[tool.name] = {
            "source": source,
            "retention": retention,
            "ephemeral": ephemeral,
            "code": code,
            "description": description or getattr(tool, "description", ""),
            "task_id": task_id,
            "saved": False,
            "skillified": False,
        }
        self._system = system_prompt(list(self._tool_registry.values()))

    @property
    def tools(self) -> list[Tool]:
        return list(self._tool_registry.values())

    def _get_tool(self, name: str) -> Tool | None:
        return self._tool_registry.get(name)

    def unregister_tool(self, name: str):
        """Remove a dynamically registered tool from the current agent."""
        meta = self._tool_meta.get(name, {})
        if name in self._tool_registry:
            del self._tool_registry[name]
        self._tool_meta.pop(name, None)
        self._system = system_prompt(list(self._tool_registry.values()))
        if meta.get("source") in {"forged", "session"} or meta.get("retention") == "ephemeral":
            self.telemetry.log(
                "tool_discarded",
                tool_name=name,
                source=meta.get("source", ""),
                retention=meta.get("retention", ""),
                description=meta.get("description", ""),
            )

    def save_tool_to_retained_library(self, name: str) -> bool:
        """Persist a tool implementation to the retained tool library."""
        meta = self._tool_meta.get(name)
        if not meta:
            return False
        code = meta.get("code")
        desc = meta.get("description")
        if not code or not desc:
            return False

        from .tool_library import get_tool_library
        lib = get_tool_library()
        if not lib.save(name, desc, code):
            return False

        meta["saved"] = True
        meta["ephemeral"] = False
        meta["source"] = "retained_library"
        meta["retention"] = "retained"
        self.telemetry.log(
            "tool_retained",
            tool_name=name,
            retention="retained",
            source=meta.get("source"),
            description=desc,
        )
        return True

    def save_tool_to_skill_library(self, name: str, skill_name: str, skill_desc: str, skill_code: str) -> bool:
        """Persist a workflow-facing skill independently of retained tool storage."""
        from .skill_library import get_library

        lib = get_library()
        if not lib.save(skill_name, skill_desc, skill_code):
            return False

        meta = self._tool_meta.get(name)
        if meta:
            meta["skillified"] = True
        self.telemetry.log(
            "skill_saved",
            tool_name=name,
            skill_name=skill_name,
            skill_source="retained_tool",
            description=skill_desc,
        )
        return True

    def retain_tool_for_session(self, name: str) -> bool:
        """Keep a forged tool available for the rest of the current process."""
        meta = self._tool_meta.get(name)
        if not meta:
            return False
        meta["ephemeral"] = False
        meta["source"] = "session"
        meta["retention"] = "session"
        self.telemetry.log(
            "tool_session_kept",
            tool_name=name,
            retention="session",
            description=meta.get("description", ""),
        )
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
        trajectory = TrajectoryRecorder(task_id)
        self.messages.append({"role": "user", "content": user_input})
        trajectory.record("user_message", content=user_input)
        self.context.maybe_compress(self.messages, self.llm)

        # Track which tools were actually called this turn
        tools_called: list[str] = []
        tool_errors: list[str] = []

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
                    trajectory.record("assistant_final", content=final_response)
                    self.telemetry.log(
                        "task_completed",
                        task_id=task_id,
                        user_query=user_input,
                        tools_called=tools_called,
                        tool_search_called=("tool_search" in tools_called),
                        skill_search_called=("skill_search" in tools_called),
                        tool_forge_called=("tool_forge" in tools_called),
                        trajectory_path=str(trajectory.path),
                    )

                    # After task completes: evaluate tool retention and/or workflow skillification
                    self._maybe_offer_skill(task_id, user_input, final_response, tools_called)
                    self._maybe_offer_skill_revision(
                        task_id,
                        user_input,
                        final_response,
                        tools_called,
                        tool_errors,
                        str(trajectory.path),
                    )
                    self._cleanup_task_tools(task_id)
                    self._active_task_id = None
                    trajectory.close("completed")
                    cleaned = True

                    return final_response

                self.messages.append(resp.message)
                trajectory.record(
                    "assistant_tool_plan",
                    tool_calls=[
                        {"name": tc.name, "arguments": tc.arguments}
                        for tc in resp.tool_calls
                    ],
                )

                if len(resp.tool_calls) == 1:
                    tc = resp.tool_calls[0]
                    tools_called.append(tc.name)
                    if on_tool:
                        on_tool(tc.name, tc.arguments)
                    result = self._exec_tool(tc)
                    if _looks_like_tool_error(result):
                        tool_errors.append(f"{tc.name}: {result[:300]}")
                    trajectory.record(
                        "tool_result",
                        tool_name=tc.name,
                        arguments=tc.arguments,
                        result=result[:4000],
                        is_error=_looks_like_tool_error(result),
                    )
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })
                else:
                    results = self._exec_tools_parallel(resp.tool_calls, on_tool)
                    for tc, result in zip(resp.tool_calls, results):
                        tools_called.append(tc.name)
                        if _looks_like_tool_error(result):
                            tool_errors.append(f"{tc.name}: {result[:300]}")
                        trajectory.record(
                            "tool_result",
                            tool_name=tc.name,
                            arguments=tc.arguments,
                            result=result[:4000],
                            is_error=_looks_like_tool_error(result),
                        )
                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        })

                self.context.maybe_compress(self.messages, self.llm)

            self._cleanup_task_tools(task_id)
            self._active_task_id = None
            trajectory.close("max_rounds")
            cleaned = True
            return "(reached maximum tool-call rounds)"
        finally:
            if not cleaned:
                self._cleanup_task_tools(task_id)
                self._active_task_id = None
                trajectory.close("interrupted")

    # -- Skill save offer ------------------------------------------------------

    def _maybe_offer_skill(
        self, task_id: int, user_input: str, response: str, tools_called: list[str]
    ):
        """After a task completes, handle tool retention and workflow skillification.

        Scoring criteria (hard rules, no LLM call needed):
          +3  used bash with non-trivial code (multi-step pipeline)
          +2  used write_file or edit_file (produced reusable artifact)
          +2  used 3+ different tools in one task
          +2  response contains a code block (generated reusable logic)
          +1  query contains reuse signals ('every time', 'always', 'script',
                'automate', 'batch', 'generate', 'parse', 'convert', 'analyze')
          -3  simple query (< 8 words and no code in response)

        Workflow-first skillification is independent of retained-tool skillification:
        a task can become a skill even if it only orchestrated existing tools or
        did not need a new tool at all.
        """
        workflow_skill_handled = False

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
                    suggestion = self.retention_engine.suggest_tool_retention(
                        user_input=user_input,
                        tool_name=name,
                        description=desc,
                        source="forged",
                        tools_called=tools_called,
                    )
                    action = self.on_tool_retention_prompt(
                        name, desc, code, "forged", suggestion.recommendation, suggestion.reasons
                    )
                    self.telemetry.log(
                        "tool_retention_decision",
                        tool_name=name,
                        source="forged",
                        recommended=suggestion.recommendation,
                        chosen=action,
                        score=suggestion.score,
                        reasons=suggestion.reasons,
                    )
                if action == "retain":
                    if self.save_tool_to_retained_library(name):
                        self._maybe_offer_skillification(name, desc, code)
                        workflow_skill_handled = True
                elif action == "session":
                    self.retain_tool_for_session(name)

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
                suggestion = self.retention_engine.suggest_tool_retention(
                    user_input=user_input,
                    tool_name=name,
                    description=desc,
                    source="session",
                    tools_called=tools_called,
                )
                action = self.on_tool_retention_prompt(
                    name, desc, code, "session", suggestion.recommendation, suggestion.reasons
                )
                self.telemetry.log(
                    "tool_retention_decision",
                    tool_name=name,
                    source="session",
                    recommended=suggestion.recommendation,
                    chosen=action,
                    score=suggestion.score,
                    reasons=suggestion.reasons,
                )
                if action == "retain":
                    if self.save_tool_to_retained_library(name):
                        self._maybe_offer_skillification(name, desc, code)
                        workflow_skill_handled = True
                elif action == "discard":
                    self.unregister_tool(name)
                elif action == "session":
                    self.retain_tool_for_session(name)

        used_retained_tools = [
            name for name in set(tools_called)
            if self._tool_meta.get(name, {}).get("retention") == "retained"
        ]
        if used_retained_tools:
            for name in used_retained_tools:
                meta = self._tool_meta.get(name, {})
                code = meta.get("code")
                desc = meta.get("description", "")
                if code and not meta.get("skillified", False):
                    self._maybe_offer_skillification(name, desc, code)
                    workflow_skill_handled = True

        if self.on_skill_prompt is None:
            return

        # If a workflow already used a saved skill, don't try to extract another skill
        # from the same run unless the caller asked through the retained-tool path.
        if any(
            self._tool_meta.get(name, {}).get("retention") == "skill"
            for name in set(tools_called)
        ):
            return

        workflow_suggestion = self.skillification_engine.suggest_workflow_skill(
            user_input=user_input,
            response=response,
            tools_called=tools_called,
        )
        self.telemetry.log(
            "workflow_skill_evaluated",
            task_id=task_id,
            recommended=workflow_suggestion.recommendation,
            score=workflow_suggestion.score,
            reasons=workflow_suggestion.reasons,
        )

        if workflow_suggestion.recommendation != "save_skill":
            return

        # Avoid double prompting after a retained-tool -> skillification path already ran.
        if workflow_skill_handled:
            return

        # Ask LLM to suggest a name + description for the skill
        skill_meta = self._suggest_skill_meta(user_input, response)
        if not skill_meta:
            return

        name, desc, code = skill_meta

        # Ask the user (via callback set by CLI)
        save = self.on_skill_prompt(
            name, desc, code, workflow_suggestion.recommendation, workflow_suggestion.reasons
        )
        self.telemetry.log(
            "workflow_skill_prompted",
            task_id=task_id,
            skill_name=name,
            chosen=bool(save),
            score=workflow_suggestion.score,
            reasons=workflow_suggestion.reasons,
        )
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
                self.register_tool(tool, source="skill_library", retention="skill")
            self.telemetry.log(
                "skill_saved",
                task_id=task_id,
                skill_name=name,
                skill_source="workflow",
                description=desc,
            )

    def _maybe_offer_skillification(self, tool_name: str, tool_desc: str, tool_code: str):
        """Optionally package a retained tool into a workflow-facing skill."""
        if self.on_skillification_prompt is None:
            return

        suggestion = self.skillification_engine.suggest_from_retained_tool(tool_name, tool_desc)
        if suggestion.recommendation != "skillify":
            return

        skill_meta = self._suggest_skill_from_retained_tool(tool_name, tool_desc, tool_code)
        if not skill_meta:
            return

        skill_name, skill_desc, skill_code = skill_meta
        save = self.on_skillification_prompt(
            tool_name, skill_name, skill_desc, skill_code, suggestion.recommendation, suggestion.reasons
        )
        self.telemetry.log(
            "retained_tool_skill_prompted",
            tool_name=tool_name,
            skill_name=skill_name,
            chosen=bool(save),
            score=suggestion.score,
            reasons=suggestion.reasons,
        )
        if not save:
            return

        self.save_tool_to_skill_library(tool_name, skill_name, skill_desc, skill_code)

    def _maybe_offer_skill_revision(
        self,
        task_id: int,
        user_input: str,
        response: str,
        tools_called: list[str],
        tool_errors: list[str],
        trajectory_path: str,
    ):
        """Let used skills accumulate lightweight revision notes from trajectories."""
        if self.on_skill_revision_prompt is None:
            return

        used_skills = [
            name for name in set(tools_called)
            if self._tool_meta.get(name, {}).get("retention") == "skill"
        ]
        if not used_skills:
            return

        trajectory_excerpt = "\n".join(
            msg.get("content", "")[:500]
            for msg in self.messages[-12:]
            if msg.get("role") in {"user", "tool", "assistant"}
        )

        for skill_name in used_skills:
            suggestion = self.skillification_engine.suggest_skill_revision(
                skill_name=skill_name,
                user_input=user_input,
                response=response,
                tools_called=tools_called,
                tool_errors=tool_errors,
            )
            self.telemetry.log(
                "skill_revision_evaluated",
                task_id=task_id,
                skill_name=skill_name,
                recommended=suggestion.recommendation,
                score=suggestion.score,
                reasons=suggestion.reasons,
                trajectory_path=trajectory_path,
            )
            if suggestion.recommendation != "revise_skill":
                continue

            note = self.skillification_engine.build_skill_revision_note(
                skill_name=skill_name,
                user_input=user_input,
                response=response,
                trajectory_excerpt=trajectory_excerpt,
            )
            if not note:
                continue

            save = self.on_skill_revision_prompt(skill_name, note, suggestion.reasons)
            self.telemetry.log(
                "skill_revision_prompted",
                task_id=task_id,
                skill_name=skill_name,
                chosen=bool(save),
                score=suggestion.score,
                reasons=suggestion.reasons,
                trajectory_path=trajectory_path,
            )
            if not save:
                continue

            from .skill_library import get_library

            if get_library().append_revision_note(
                skill_name,
                note,
                task_id=task_id,
                trajectory_path=trajectory_path,
            ):
                self.telemetry.log(
                    "skill_revised",
                    task_id=task_id,
                    skill_name=skill_name,
                    note=note,
                    trajectory_path=trajectory_path,
                )

    def _suggest_skill_from_retained_tool(
        self, tool_name: str, tool_desc: str, tool_code: str
    ) -> tuple[str, str, str] | None:
        """Wrap a retained tool as an explicit skill when the workflow is worth promoting."""
        return self.skillification_engine.build_skill_from_retained_tool(
            tool_name, tool_desc, tool_code
        )

    def _suggest_skill_meta(
        self, user_input: str, response: str
    ) -> tuple[str, str, str] | None:
        """Extract a workflow-facing skill even when no new tool was retained."""
        # Gather the bash commands / code blocks from recent tool results
        recent_tool_results = []
        for msg in self.messages[-20:]:
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                if content and len(content) < 2000:
                    recent_tool_results.append(content)

        return self.skillification_engine.build_skill_from_workflow(
            user_input, response, recent_tool_results
        )

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


def _looks_like_tool_error(result: str) -> bool:
    text = (result or "").strip().lower()
    return text.startswith("error") or "error executing" in text or "user denied" in text
