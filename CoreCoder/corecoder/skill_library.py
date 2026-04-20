# -*- coding: utf-8 -*-
"""Skill Library - persistent storage and retrieval of dynamically generated tools.

Skills are Tool subclasses generated at runtime and saved to disk.
They are NOT loaded into the agent's context by default - the agent must
explicitly search for and load them via SkillSearchTool.

Directory layout:
  skill_store/
  +-- index.json                  # global index: name -> metadata
  +-- py_file_analyzer/
  |   +-- skill.py                # generated Tool class source
  |   +-- meta.json               # per-skill metadata (description, tags, ...)
  +-- csv_analyzer/
      +-- skill.py
      +-- meta.json
"""

from __future__ import annotations

import ast
import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tools.base import Tool

# Default location: CoreCoder package root / skill_store
_DEFAULT_DIR = Path(__file__).parent / "skill_store"


class SkillLibrary:
    """Manages skill persistence and keyword-based retrieval."""

    def __init__(self, directory: Path | str | None = None):
        self.dir = Path(directory) if directory else _DEFAULT_DIR
        self.dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.dir / "index.json"

    # ---- Index I/O -----------------------------------------------------------

    def _load_index(self) -> dict:
        if self._index_path.exists():
            try:
                return json.loads(self._index_path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_index(self, index: dict):
        self._index_path.write_text(
            json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ---- Save ----------------------------------------------------------------

    def save(self, name: str, description: str, code: str, tags: list[str] | None = None) -> bool:
        """Persist a generated tool to disk under skill_store/<name>/. Returns True on success."""
        try:
            skill_dir = self.dir / name
            skill_dir.mkdir(parents=True, exist_ok=True)

            # Write source code
            (skill_dir / "skill.py").write_text(code, encoding="utf-8")

            # Write per-skill meta.json
            meta = {
                "name": name,
                "description": description,
                "tags": tags or _extract_tags(description),
                "use_count": 0,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            (skill_dir / "meta.json").write_text(
                json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            # Update global index
            index = self._load_index()
            index[name] = {
                "dir": name,                        # subfolder name
                "description": description,
                "tags": meta["tags"],
                "use_count": 0,
                "created_at": meta["created_at"],
            }
            self._save_index(index)
            return True
        except Exception:
            return False

    # ---- Search --------------------------------------------------------------

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Keyword-based search over skill descriptions and tags.

        Returns a ranked list of skill metadata dicts (best match first).
        No vectors, no external deps -- pure token overlap scoring.
        """
        index = self._load_index()
        if not index:
            return []

        query_tokens = _tokenize(query)
        scored: list[tuple[float, dict]] = []

        for name, meta in index.items():
            desc_tokens = _tokenize(meta.get("description", ""))
            tag_tokens: list[str] = []
            for t in meta.get("tags", []):
                tag_tokens.extend(_tokenize(t))

            # tags weighted 2x vs description
            desc_score = _overlap(query_tokens, desc_tokens)
            tag_score  = _overlap(query_tokens, tag_tokens) * 2.0
            score = desc_score + tag_score

            if score > 0:
                scored.append((score, {"name": name, **meta}))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:top_k]]

    # ---- Semantic search (LLM re-ranking) ------------------------------------

    def semantic_search(
        self, query: str, candidates: list[dict], llm, top_k: int = 3
    ) -> list[dict]:
        """Re-rank keyword candidates using LLM semantic judgment.

        Falls back to returning candidates[:top_k] if the LLM call fails.
        """
        if not candidates:
            return []
        if len(candidates) <= top_k:
            return candidates  # no need to re-rank

        skill_list = "\n".join(
            f"- {m['name']}: {m.get('description', '')}" for m in candidates
        )
        prompt = (
            "You are a skill retrieval system. Given a user query and a list of "
            f"candidate skills, return a JSON array of the {top_k} most relevant "
            "skill names. If none are relevant, return [].\n\n"
            f"User query: {query}\n\n"
            f"Candidate skills:\n{skill_list}\n\n"
            "Return ONLY a JSON array of skill name strings, e.g. "
            '["skill_a", "skill_b"]. No explanation.'
        )
        try:
            resp = llm.chat(
                messages=[
                    {"role": "system", "content": "You output only valid JSON arrays."},
                    {"role": "user", "content": prompt},
                ],
            )
            text = resp.content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            names = json.loads(text)
            if isinstance(names, list):
                name_set = {m["name"] for m in candidates}
                valid_names = [n for n in names if n in name_set][:top_k]
                name_to_meta = {m["name"]: m for m in candidates}
                return [name_to_meta[n] for n in valid_names if n in name_to_meta]
        except Exception:
            pass
        return candidates[:top_k]

    # ---- Load ----------------------------------------------------------------

    def load(self, name: str) -> "Tool | None":
        """Instantiate a skill by name. Returns None if not found or broken."""
        index = self._load_index()
        if name not in index:
            return None

        skill_file = self.dir / index[name]["dir"] / "skill.py"
        if not skill_file.exists():
            return None

        code = skill_file.read_text(encoding="utf-8")
        return _instantiate_tool(code)

    def load_many(self, names: list[str]) -> list["Tool"]:
        """Load multiple skills, silently skipping failures."""
        tools = []
        for name in names:
            t = self.load(name)
            if t:
                tools.append(t)
        return tools

    # ---- Use count -----------------------------------------------------------

    def increment_use(self, name: str):
        index = self._load_index()
        if name in index:
            index[name]["use_count"] = index[name].get("use_count", 0) + 1
            self._save_index(index)
            # also update per-skill meta.json
            meta_path = self.dir / index[name]["dir"] / "meta.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    meta["use_count"] = index[name]["use_count"]
                    meta_path.write_text(
                        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
                    )
                except Exception:
                    pass

    # ---- List ----------------------------------------------------------------

    def list_all(self) -> list[dict]:
        """Return all skill metadata sorted by use_count desc."""
        index = self._load_index()
        items = [{"name": k, **v} for k, v in index.items()]
        items.sort(key=lambda x: x.get("use_count", 0), reverse=True)
        return items

    def exists(self, name: str) -> bool:
        return name in self._load_index()


# ---- Helpers -----------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumeric, filter short tokens."""
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return [t for t in tokens if len(t) > 1]


def _overlap(a: list[str], b: list[str]) -> float:
    """Jaccard-like overlap: |intersection| / sqrt(|a|*|b|) to avoid length bias."""
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    inter = len(sa & sb)
    if inter == 0:
        return 0.0
    return inter / (len(sa) * len(sb)) ** 0.5


def _extract_tags(description: str) -> list[str]:
    """Auto-extract likely tags from a description."""
    stopwords = {
        "with", "from", "that", "this", "will", "have", "been", "they",
        "their", "when", "where", "which", "return", "returns", "given",
        "using", "based", "into", "over", "each", "also", "more",
    }
    tokens = re.findall(r"[a-zA-Z]{4,}", description)
    seen: set[str] = set()
    tags: list[str] = []
    for t in tokens:
        tl = t.lower()
        if tl not in stopwords and tl not in seen:
            seen.add(tl)
            tags.append(tl)
    return tags[:10]


def _instantiate_tool(code: str) -> "Tool | None":
    """exec() the code and return an instance of the first Tool subclass found."""
    try:
        from .tools.base import Tool
        ast.parse(code)
        namespace: dict = {}
        exec("from corecoder.tools.base import Tool", namespace)
        exec(code, namespace)
        for obj in namespace.values():
            if isinstance(obj, type) and issubclass(obj, Tool) and obj is not Tool:
                return obj()
    except Exception:
        pass
    return None


# ---- Module-level singleton --------------------------------------------------

_library: SkillLibrary | None = None


def get_library(directory: Path | str | None = None) -> SkillLibrary:
    """Return the module-level SkillLibrary singleton."""
    global _library
    if _library is None:
        _library = SkillLibrary(directory)
    return _library
