"""Skill Manager - persistent, on-demand tool library.

Skills are Tool subclasses created by the agent at runtime and saved to disk.
On future queries, relevant skills are retrieved via LLM judgment and
dynamically loaded into the agent's tool list.

Storage layout:
    ~/.corecoder/skills/
    ├── index.json          # {name: {description, file, created_at, usage_count}}
    ├── regex_extract.py    # Tool subclass source
    └── ...
"""

import ast
import json
import sys
from datetime import datetime
from pathlib import Path

from .tools.base import Tool


class SkillManager:
    def __init__(self, library_dir: str | Path | None = None):
        if library_dir is None:
            library_dir = Path.home() / ".corecoder" / "skills"
        self.library_dir = Path(library_dir)
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self._index_file = self.library_dir / "index.json"
        self._loaded: dict[str, Tool] = {}  # cache of loaded skill instances

    # ── Index operations ──────────────────────────────────────────

    def _read_index(self) -> dict:
        if self._index_file.exists():
            return json.loads(self._index_file.read_text(encoding="utf-8"))
        return {}

    def _write_index(self, index: dict):
        self._index_file.write_text(
            json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def list_skills(self) -> list[dict]:
        """Return a list of {name, description} for all saved skills."""
        index = self._read_index()
        return [
            {"name": name, "description": info["description"]}
            for name, info in index.items()
        ]

    def get_index_summary(self) -> str:
        """Return a brief text summary of all skills (for prompts)."""
        skills = self.list_skills()
        if not skills:
            return ""
        lines = [f"- {s['name']}: {s['description']}" for s in skills]
        return "\n".join(lines)

    # ── LLM-based retrieval ───────────────────────────────────────

    def retrieve(self, query: str, llm, top_k: int = 3) -> list[str]:
        """Use LLM to judge which skills are relevant to the query.

        Returns a list of skill names to load. If the skill library is empty,
        returns [] immediately without calling the LLM.
        """
        index = self._read_index()
        if not index:
            return []

        skill_list = "\n".join(
            f"- {name}: {info['description']}" for name, info in index.items()
        )

        prompt = (
            "You are a skill retrieval system. Given a user query and a list of "
            "available skills, return a JSON array of skill names that are relevant "
            "to the query. Return at most {top_k} skills. If none are relevant, "
            "return an empty array [].\n\n"
            f"Available skills:\n{skill_list}\n\n"
            f"User query: {query}\n\n"
            "Return ONLY a JSON array of skill name strings, nothing else. "
            'Example: ["regex_extract", "json_query"]'
        )

        try:
            resp = llm.chat(
                messages=[
                    {"role": "system", "content": "You output only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
            )
            # Parse the JSON array from response
            text = resp.content.strip()
            # Handle markdown code block wrapping
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            names = json.loads(text)
            if isinstance(names, list):
                # Filter to only valid skill names
                valid = [n for n in names if n in index]
                return valid[:top_k]
        except Exception:
            pass
        return []

    # ── Load / Save ───────────────────────────────────────────────

    def load(self, name: str) -> Tool | None:
        """Load a skill by name, returning a Tool instance. Uses cache."""
        if name in self._loaded:
            return self._loaded[name]

        index = self._read_index()
        if name not in index:
            return None

        tool_file = self.library_dir / index[name]["file"]
        if not tool_file.exists():
            return None

        code = tool_file.read_text(encoding="utf-8")
        namespace = {}
        # Provide CoreCoder's Tool base class
        namespace["__builtins__"] = __builtins__
        exec("from corecoder.tools.base import Tool", namespace)

        try:
            exec(code, namespace)
        except Exception:
            return None

        for obj in namespace.values():
            if isinstance(obj, type) and issubclass(obj, Tool) and obj is not Tool:
                try:
                    instance = obj()
                    self._loaded[name] = instance
                    # Update usage count
                    index[name]["usage_count"] = index[name].get("usage_count", 0) + 1
                    self._write_index(index)
                    return instance
                except Exception:
                    return None

        return None

    def save(self, name: str, description: str, code: str) -> str:
        """Validate and save a skill. Returns a message string."""
        # Validate first
        result = self.validate(code)
        if not result["success"]:
            return f"Skill validation failed: {result['error']}"

        # Save source file
        tool_file = self.library_dir / f"{name}.py"
        tool_file.write_text(code, encoding="utf-8")

        # Update index
        index = self._read_index()
        index[name] = {
            "description": description,
            "file": f"{name}.py",
            "created_at": datetime.now().isoformat(),
            "usage_count": 0,
        }
        self._write_index(index)

        # Clear cache so next load picks up the new version
        self._loaded.pop(name, None)

        return f"Skill '{name}' saved to {tool_file}"

    # ── Validation ────────────────────────────────────────────────

    def validate(self, code: str) -> dict:
        """Validate skill code. Returns {success: bool, error: str|None}."""
        # 1. Syntax check
        try:
            ast.parse(code)
        except SyntaxError as e:
            return {"success": False, "error": f"Syntax error: {e}"}

        # 2. Execute and find Tool subclass
        namespace = {}
        exec("from corecoder.tools.base import Tool", namespace)
        try:
            exec(code, namespace)
        except Exception as e:
            return {"success": False, "error": f"Import/exec error: {e}"}

        tool_cls = None
        for obj in namespace.values():
            if isinstance(obj, type) and issubclass(obj, Tool) and obj is not Tool:
                tool_cls = obj
                break

        if tool_cls is None:
            return {"success": False, "error": "No Tool subclass found in code"}

        # 3. Verify schema
        try:
            instance = tool_cls()
            schema = instance.schema()
            assert "function" in schema
            assert "name" in schema["function"]
            assert "parameters" in schema["function"]
        except Exception as e:
            return {"success": False, "error": f"Schema error: {e}"}

        return {"success": True, "error": None}
