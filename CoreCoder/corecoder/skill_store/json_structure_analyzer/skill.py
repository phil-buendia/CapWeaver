import json
from collections import Counter
from corecoder.tools.base import Tool


class JsonStructureAnalyzerTool(Tool):
    name = "json_structure_analyzer"
    description = "Analyze a JSON file and produce a structured summary report."
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Path to the JSON file"},
        },
        "required": ["file_path"],
    }

    def _json_type(self, value):
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            return "int"
        if isinstance(value, float):
            return "float"
        if isinstance(value, str):
            return "str"
        if isinstance(value, dict):
            return "object"
        if isinstance(value, list):
            return "array"
        return "unknown"

    def execute(self, **kwargs) -> str:
        file_path = kwargs.get("file_path", "")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return f"Error: File not found: {file_path}"
        except json.JSONDecodeError as e:
            return f"Error: Invalid JSON: {e}"
        except Exception as e:
            return f"Error: {e}"

        if not isinstance(data, dict):
            return f"Error: Top-level JSON must be an object, got {self._json_type(data)}"

        result = {"file": file_path, "top_level_key_count": len(data), "keys": {}}
        lines = [f"JSON Structure Report: {file_path}",
                 f"Top-level keys: {len(data)}"]

        for key, value in data.items():
            vtype = self._json_type(value)
            key_info = {"type": vtype}
            lines.append(f"  [{key}] -> {vtype}")

            if isinstance(value, dict):
                sub_keys = list(value.keys())
                key_info["sub_key_count"] = len(sub_keys)
                key_info["sub_keys"] = sub_keys
                lines.append(f"    sub-keys ({len(sub_keys)}): {sub_keys}")

            elif isinstance(value, list):
                length = len(value)
                type_dist = Counter(self._json_type(el) for el in value)
                key_info["length"] = length
                key_info["element_type_distribution"] = dict(type_dist)
                lines.append(f"    length: {length}, types: {dict(type_dist)}")
                if value and isinstance(value[0], dict):
                    schema_hint = list(value[0].keys())
                    key_info["schema_hint"] = schema_hint
                    lines.append(f"    schema hint (first element keys): {schema_hint}")

            result["keys"][key] = key_info

        report = "\n".join(lines)
        print(report)
        return json.dumps(result, indent=2)