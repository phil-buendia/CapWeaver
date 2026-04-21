# -*- coding: utf-8 -*-
"""Retained Tool Library - persistent storage for reusable Tool implementations.

Unlike skills, retained tools are saved as executable building blocks. They do
not imply that the surrounding business workflow is worth publishing as a
skill. They live in a separate `tool_store/` and are retrieved through
tool_search.
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

_DEFAULT_DIR = Path(__file__).parent / "tool_store"


class ToolLibrary:
    """Persistent storage and retrieval for retained tools."""

    def __init__(self, directory: Path | str | None = None):
        self.dir = Path(directory) if directory else _DEFAULT_DIR
        self.dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.dir / "index.json"

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

    def save(
        self, name: str, description: str, code: str, tags: list[str] | None = None
    ) -> bool:
        """Persist a retained tool under tool_store/<name>/."""
        try:
            tool_dir = self.dir / name
            tool_dir.mkdir(parents=True, exist_ok=True)

            (tool_dir / "tool.py").write_text(code, encoding="utf-8")
            meta = {
                "name": name,
                "description": description,
                "tags": tags or _extract_tags(description),
                "use_count": 0,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            (tool_dir / "meta.json").write_text(
                json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            index = self._load_index()
            index[name] = {
                "dir": name,
                "description": description,
                "tags": meta["tags"],
                "use_count": 0,
                "created_at": meta["created_at"],
            }
            self._save_index(index)
            return True
        except Exception:
            return False

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        index = self._load_index()
        if not index:
            return []

        query_tokens = _tokenize(query)
        scored: list[tuple[float, dict]] = []
        for name, meta in index.items():
            desc_tokens = _tokenize(meta.get("description", ""))
            tag_tokens: list[str] = []
            for tag in meta.get("tags", []):
                tag_tokens.extend(_tokenize(tag))
            score = _overlap(query_tokens, desc_tokens) + _overlap(query_tokens, tag_tokens) * 2.0
            if score > 0:
                scored.append((score, {"name": name, **meta}))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [meta for _, meta in scored[:top_k]]

    def semantic_search(
        self, query: str, candidates: list[dict], llm, top_k: int = 3
    ) -> list[dict]:
        if not candidates:
            return []
        if len(candidates) <= top_k:
            return candidates

        tool_list = "\n".join(
            f"- {meta['name']}: {meta.get('description', '')}" for meta in candidates
        )
        prompt = (
            "You are a retained-tool retrieval system. Given a user query and a list of "
            f"candidate tools, return a JSON array of the {top_k} most relevant tool names. "
            "If none are relevant, return [].\n\n"
            f"User query: {query}\n\n"
            f"Candidate tools:\n{tool_list}\n\n"
            'Return ONLY a JSON array, e.g. ["tool_a", "tool_b"].'
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
                name_set = {meta["name"] for meta in candidates}
                valid = [name for name in names if name in name_set][:top_k]
                lookup = {meta["name"]: meta for meta in candidates}
                return [lookup[name] for name in valid if name in lookup]
        except Exception:
            pass
        return candidates[:top_k]

    def load(self, name: str) -> "Tool | None":
        index = self._load_index()
        if name not in index:
            return None
        tool_file = self.dir / index[name]["dir"] / "tool.py"
        if not tool_file.exists():
            return None
        code = tool_file.read_text(encoding="utf-8")
        return _instantiate_tool(code)

    def load_code(self, name: str) -> str | None:
        index = self._load_index()
        if name not in index:
            return None
        tool_file = self.dir / index[name]["dir"] / "tool.py"
        if not tool_file.exists():
            return None
        try:
            return tool_file.read_text(encoding="utf-8")
        except Exception:
            return None

    def list_all(self) -> list[dict]:
        items = [{"name": name, **meta} for name, meta in self._load_index().items()]
        items.sort(key=lambda item: item.get("use_count", 0), reverse=True)
        return items

    def increment_use(self, name: str):
        index = self._load_index()
        if name not in index:
            return
        index[name]["use_count"] = index[name].get("use_count", 0) + 1
        self._save_index(index)
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

    def exists(self, name: str) -> bool:
        return name in self._load_index()


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return [token for token in tokens if len(token) > 1]


def _overlap(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    inter = len(sa & sb)
    if inter == 0:
        return 0.0
    return inter / (len(sa) * len(sb)) ** 0.5


def _extract_tags(description: str) -> list[str]:
    stopwords = {
        "with", "from", "that", "this", "will", "have", "been", "they",
        "their", "when", "where", "which", "return", "returns", "given",
        "using", "based", "into", "over", "each", "also", "more",
    }
    tokens = re.findall(r"[a-zA-Z]{4,}", description)
    seen: set[str] = set()
    tags: list[str] = []
    for token in tokens:
        lowered = token.lower()
        if lowered not in stopwords and lowered not in seen:
            seen.add(lowered)
            tags.append(lowered)
    return tags[:10]


def _instantiate_tool(code: str) -> "Tool | None":
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


_library: ToolLibrary | None = None


def get_tool_library(directory: Path | str | None = None) -> ToolLibrary:
    global _library
    if _library is None:
        _library = ToolLibrary(directory)
    return _library
