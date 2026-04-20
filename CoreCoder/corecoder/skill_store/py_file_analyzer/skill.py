from corecoder.tools.base import Tool
import ast
from pathlib import Path


class PyFileAnalyzerTool(Tool):
    name = "py_file_analyzer"
    description = "Analyze all Python files in a directory: count lines, functions, and classes per file using AST parsing."
    parameters = {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Directory to scan (default: current directory '.')",
            },
        },
        "required": [],
    }

    def execute(self, directory: str = ".") -> str:
        results = []
        for fp in Path(directory).rglob("*.py"):
            if "__pycache__" in str(fp):
                continue
            try:
                src = fp.read_text(encoding="utf-8", errors="ignore")
                lines = len(src.splitlines())
                tree = ast.parse(src)
                funcs = sum(1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
                classes = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
                results.append((str(fp), lines, funcs, classes))
            except Exception:
                results.append((str(fp), 0, 0, 0))

        if not results:
            return f"No Python files found in '{directory}'."

        results.sort(key=lambda x: x[1], reverse=True)

        lines_out = [f"{'File':<55} {'Lines':>6} {'Funcs':>6} {'Classes':>8}"]
        lines_out.append("-" * 80)
        for fp, lines, funcs, classes in results:
            lines_out.append(f"{fp:<55} {lines:>6} {funcs:>6} {classes:>8}")
        lines_out.append("-" * 80)
        total_lines = sum(r[1] for r in results)
        total_funcs = sum(r[2] for r in results)
        total_classes = sum(r[3] for r in results)
        lines_out.append(
            f"Total: {len(results)} files, {total_lines} lines, "
            f"{total_funcs} funcs, {total_classes} classes"
        )
        return "\n".join(lines_out)
