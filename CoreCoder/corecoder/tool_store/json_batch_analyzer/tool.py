import json
import glob
import os
from collections import defaultdict
from corecoder.tools.base import Tool

class JsonBatchAnalyzerTool(Tool):
    name = "json_batch_analyzer"
    description = "Reusable 3-step JSON structure analysis workflow across multiple files."
    parameters = {
        "type": "object",
        "properties": {
            "directory": {"type": "string", "description": "Root directory", "default": "."},
            "pattern": {"type": "string", "description": "Glob pattern", "default": "**/*.json"},
            "exclude": {"type": "array", "items": {"type": "string"}, "description": "Exclude patterns"},
        },
        "required": [],
    }

    def _jtype(self, v):
        if v is None: return "null"
        if isinstance(v, bool): return "bool"
        if isinstance(v, int): return "int"
        if isinstance(v, float): return "float"
        if isinstance(v, str): return "str"
        if isinstance(v, dict): return "object"
        if isinstance(v, list): return "array"
        return "unknown"

    def _analyze(self, data):
        if not isinstance(data, dict):
            return {"error": f"Top-level is {self._jtype(data)}, not object"}
        info = {"key_count": len(data), "keys": {}}
        for k, v in data.items():
            t = self._jtype(v)
            entry = {"type": t}
            if t == "object":
                entry["sub_keys"] = list(v.keys())
            if t == "array":
                entry["length"] = len(v)
                dist = defaultdict(int)
                for el in v: dist[self._jtype(el)] += 1
                entry["element_types"] = dict(dist)
                if dist.get("object") == len(v) and v:
                    all_keys = set()
                    for el in v:
                        if isinstance(el, dict): all_keys.update(el.keys())
                    entry["schema_hint"] = sorted(all_keys)
            info["keys"][k] = entry
        return info

    def execute(self, directory=".", pattern="**/*.json", exclude=None, **kwargs):
        try:
            exclude = exclude or ["__pycache__"]
            full_pattern = os.path.join(directory, pattern)
            files = glob.glob(full_pattern, recursive=True)
            files = [f for f in files if not any(ex in f for ex in exclude)]
            if not files:
                return f"No JSON files found in '{directory}' with pattern '{pattern}'."
            results, lines = {}, []
            lines.append(f"=== JSON Batch Analysis: {len(files)} file(s) ===\n")
            for fp in sorted(files):
                try:
                    with open(fp, encoding="utf-8") as fh:
                        data = json.load(fh)
                    info = self._analyze(data)
                    results[fp] = info
                    lines.append(f"-- {fp} --")
                    if "error" in info:
                        lines.append(f"  Error: {info['error']}")
                    else:
                        lines.append(f"  Top-level keys ({info['key_count']}): {list(info['keys'].keys())}")
                        for k, e in info["keys"].items():
                            detail = f"  [{k}]: {e['type']}"
                            if "sub_keys" in e: detail += f" sub_keys={e['sub_keys']}"
                            if "length" in e: detail += f" len={e['length']} elem_types={e['element_types']}"
                            if "schema_hint" in e: detail += f" schema={e['schema_hint']}"
                            lines.append(detail)
                except Exception as ex:
                    results[fp] = {"error": str(ex)}
                    lines.append(f"-- {fp} -- ERROR: {ex}")
            lines.append("\n=== Cross-File Comparison ===")
            key_types = defaultdict(lambda: defaultdict(set))
            for fp, info in results.items():
                if "keys" in info:
                    for k, e in info["keys"].items():
                        key_types[k][e["type"]].add(fp)
            all_keys = set(key_types.keys())
            file_keys = {fp: set(info.get("keys", {}).keys()) for fp, info in results.items()}
            shared = all_keys.copy()
            for ks in file_keys.values(): shared &= ks
            lines.append(f"  Shared keys ({len(shared)}): {sorted(shared)}")
            for fp, ks in file_keys.items():
                unique = ks - shared
                if unique: lines.append(f"  Unique to {fp}: {sorted(unique)}")
            lines.append("  Type anomalies:")
            found = False
            for k, tmap in key_types.items():
                if len(tmap) > 1:
                    found = True
                    lines.append(f"    '{k}' has inconsistent types: { {t: list(fps) for t, fps in tmap.items()} }")
            if not found: lines.append("    None detected.")
            return "\n".join(lines)
        except Exception as ex:
            return f"json_batch_analyzer error: {ex}"