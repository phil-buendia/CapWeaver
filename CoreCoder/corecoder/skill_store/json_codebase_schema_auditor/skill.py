from corecoder.tools.base import Tool
from corecoder.tool_library import get_tool

class JsonCodebaseSchemaAuditorTool(Tool):
    name = "json_codebase_schema_auditor"
    description = "Audits all JSON files in a codebase directory by analyzing their structure, key types, nested schemas, and cross-file consistency in a single workflow."
    parameters = {
        "type": "object",
        "properties": {
            "directory": {"type": "string", "description": "Root directory to scan for JSON files.", "default": "."},
            "pattern": {"type": "string", "description": "Glob pattern for matching JSON files.", "default": "**/*.json"},
            "exclude": {"type": "array", "items": {"type": "string"}, "description": "List of path substrings to exclude.", "default": ["__pycache__"]}
        },
        "required": []
    }

    def execute(self, directory=".", pattern="**/*.json", exclude=None, **kwargs):
        try:
            tool = get_tool("json_batch_analyzer")
            result = tool.execute(
                directory=directory,
                pattern=pattern,
                exclude=exclude if exclude is not None else ["__pycache__"]
            )
            return str(result)
        except Exception as ex:
            return f"json_codebase_schema_auditor error: {ex}"