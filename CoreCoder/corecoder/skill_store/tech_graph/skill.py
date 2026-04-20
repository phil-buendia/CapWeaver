"""
tech_graph skill - Generate production-quality SVG/PNG technical diagrams.

Wraps the fireworks-tech-graph generator:
  https://github.com/yizhiyanhua-ai/fireworks-tech-graph

Supports 14 diagram types x 7 visual styles.

Setup:
  The fireworks-tech-graph repo must be cloned locally.
  Set env var FIREWORKS_TECH_GRAPH_DIR to its path, e.g.:
    set FIREWORKS_TECH_GRAPH_DIR=D:/path/to/fireworks-tech-graph
  If not set, defaults to a sibling folder named "fireworks-tech-graph"
  next to the NanoCoder project.
"""

from corecoder.tools.base import Tool
import json
import os
import subprocess
import sys
from pathlib import Path

DIAGRAM_TYPES = [
    "architecture", "data-flow", "flowchart", "sequence",
    "comparison", "timeline", "mind-map", "agent", "memory",
    "use-case", "class", "state-machine", "er-diagram", "network-topology",
]

STYLE_NAMES = {
    1: "Flat Icon (default, white bg)",
    2: "Dark Terminal (dark bg, neon)",
    3: "Blueprint (deep blue, grid)",
    4: "Notion Clean (minimal white)",
    5: "Glassmorphism (dark gradient)",
    6: "Claude Official (warm cream)",
    7: "OpenAI Official (pure white)",
}


def _find_repo() -> Path:
    """Locate the fireworks-tech-graph repo directory.

    Priority:
    1. Env var FIREWORKS_TECH_GRAPH_DIR
    2. Sibling of the skill_store directory (walk up from this file)
    3. Sibling of the current working directory
    """
    # 1. Explicit env var
    env = os.environ.get("FIREWORKS_TECH_GRAPH_DIR")
    if env:
        return Path(env)

    # 2. Walk up from __file__ if available (normal import)
    try:
        base = Path(__file__).resolve()
        for parent in base.parents:
            candidate = parent / "fireworks-tech-graph"
            if (candidate / "scripts" / "generate-from-template.py").exists():
                return candidate
    except NameError:
        pass  # __file__ not defined in exec() context

    # 3. Walk up from cwd
    for parent in [Path.cwd()] + list(Path.cwd().parents):
        candidate = parent / "fireworks-tech-graph"
        if (candidate / "scripts" / "generate-from-template.py").exists():
            return candidate

    # 4. Fallback: return expected path even if it doesn't exist (error shown later)
    return Path.cwd().parent / "fireworks-tech-graph"


class TechGraphTool(Tool):
    name = "tech_graph"
    description = (
        "Generate a production-quality SVG + PNG technical diagram from a JSON "
        "description. Supports 14 diagram types: architecture, data-flow, flowchart, "
        "sequence, agent, memory, use-case, class, state-machine, er-diagram, "
        "network-topology, comparison, timeline, mind-map. "
        "Supports 7 visual styles (flat, dark, blueprint, notion, glass, claude, openai). "
        "Use this when the user asks to draw, visualize, or generate any diagram, "
        "architecture chart, flow chart, UML diagram, or technical illustration."
    )
    parameters = {
        "type": "object",
        "properties": {
            "diagram_type": {
                "type": "string",
                "description": (
                    "Diagram type. One of: architecture, data-flow, flowchart, "
                    "sequence, agent, memory, use-case, class, state-machine, "
                    "er-diagram, network-topology, comparison, timeline, mind-map."
                ),
                "enum": [
                    "architecture", "data-flow", "flowchart", "sequence",
                    "comparison", "timeline", "mind-map", "agent", "memory",
                    "use-case", "class", "state-machine", "er-diagram", "network-topology",
                ],
            },
            "output_path": {
                "type": "string",
                "description": (
                    "Output SVG file path, e.g. './my-diagram.svg'. "
                    "A matching .png will be exported alongside it if rsvg-convert is available."
                ),
            },
            "data": {
                "type": "object",
                "description": (
                    "Diagram data as a JSON object. "
                    "Common keys: title (str), subtitle (str), style (int 1-7), "
                    "nodes (list of node objects), arrows (list of arrow objects), "
                    "sections (list of section/group objects). "
                    "Node example: {\"id\":\"llm\",\"label\":\"LLM\",\"type\":\"model\","
                    "\"x\":480,\"y\":300,\"w\":140,\"h\":60}. "
                    "Arrow example: {\"source\":\"user\",\"target\":\"llm\","
                    "\"label\":\"query\",\"flow\":\"control\"}. "
                    "Flow types: control, write, read, data, async, feedback, neutral."
                ),
            },
            "style": {
                "type": "integer",
                "description": (
                    "Visual style 1-7. "
                    "1=Flat Icon (default), 2=Dark Terminal, 3=Blueprint, "
                    "4=Notion Clean, 5=Glassmorphism, 6=Claude Official, 7=OpenAI Official."
                ),
                "enum": [1, 2, 3, 4, 5, 6, 7],
            },
            "export_png": {
                "type": "boolean",
                "description": (
                    "Export PNG via rsvg-convert after SVG generation. "
                    "Default true. Requires rsvg-convert installed."
                ),
            },
        },
        "required": ["diagram_type", "output_path", "data"],
    }

    def execute(
        self,
        diagram_type: str,
        output_path: str,
        data: dict,
        style: int = 1,
        export_png: bool = True,
    ) -> str:
        # Locate repo at call time (avoids __file__ issues in exec context)
        repo_dir = _find_repo()
        generator = repo_dir / "scripts" / "generate-from-template.py"

        if not generator.exists():
            return (
                "[ERROR] fireworks-tech-graph repo not found.\n"
                "Searched: " + str(repo_dir) + "\n"
                "Fix options:\n"
                "  1. Set env var: FIREWORKS_TECH_GRAPH_DIR=D:/path/to/fireworks-tech-graph\n"
                "  2. Clone repo as a sibling of NanoCoder:\n"
                "     git clone https://github.com/yizhiyanhua-ai/fireworks-tech-graph.git"
            )

        # Validate diagram type
        if diagram_type not in DIAGRAM_TYPES:
            return (
                "[ERROR] Unknown diagram_type " + repr(diagram_type) + ". "
                "Valid types: " + ", ".join(DIAGRAM_TYPES)
            )

        # Inject style into data if not already set
        data_with_style = dict(data)
        if "style" not in data_with_style:
            data_with_style["style"] = style

        # Resolve output path
        svg_path = Path(output_path).resolve()
        svg_path.parent.mkdir(parents=True, exist_ok=True)

        # Build and run generator command
        data_json = json.dumps(data_with_style, ensure_ascii=False)
        cmd = [sys.executable, str(generator), diagram_type, str(svg_path), data_json]

        # Force UTF-8 I/O so Windows GBK terminal doesn't break on Unicode output
        run_env = dict(os.environ)
        run_env["PYTHONIOENCODING"] = "utf-8"

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                cwd=str(repo_dir),
                env=run_env,
            )
        except subprocess.TimeoutExpired:
            return "[ERROR] Diagram generation timed out (60s)."
        except Exception as exc:
            return "[ERROR] Failed to run generator: " + str(exc)

        if result.returncode != 0:
            err = (result.stderr or result.stdout or "unknown error").strip()
            return "[ERROR] Generator failed (exit " + str(result.returncode) + "):\n" + err

        if not svg_path.exists():
            return (
                "[ERROR] Generator exited 0 but SVG not found at " + str(svg_path) + ".\n"
                "stdout: " + result.stdout.strip()
            )

        output_lines = [
            "[OK] SVG generated: " + str(svg_path),
            "     Style: " + STYLE_NAMES.get(style, str(style)),
            "     Diagram type: " + diagram_type,
        ]

        # Export PNG if requested
        if export_png:
            png_path = svg_path.with_suffix(".png")
            try:
                png_result = subprocess.run(
                    ["rsvg-convert", "-w", "1920", str(svg_path), "-o", str(png_path)],
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )
                if png_result.returncode == 0 and png_path.exists():
                    output_lines.append("[OK] PNG exported:  " + str(png_path))
                else:
                    output_lines.append(
                        "[WARN] PNG export failed. "
                        "Install rsvg-convert: sudo apt install librsvg2-bin  "
                        "or: brew install librsvg"
                    )
            except FileNotFoundError:
                output_lines.append(
                    "[WARN] rsvg-convert not found. SVG is ready but PNG was not exported.\n"
                    "       Install: sudo apt install librsvg2-bin  or: brew install librsvg"
                )

        if result.stdout.strip():
            output_lines.append("\nGenerator output:\n" + result.stdout.strip())

        return "\n".join(output_lines)
