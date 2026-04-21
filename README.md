# CapWeaver

CapWeaver is a lightweight coding agent project focused on **capability growth**.

It starts from the compact architecture of [CoreCoder](https://github.com/he-yufeng/CoreCoder), and extends it with a more explicit capability loop:

- retrieve reusable retained tools or workflow skills
- forge a new task-scoped tool only when retrieval misses
- run the task first
- decide whether to discard, keep for the session, retain as a persistent tool, or package the workflow as a skill

Current public release: **v0.2.0**

## Why This Project

Most coding agents can finish a task, but they do not naturally get better at similar tasks over time. CapWeaver explores a more explicit direction:

**turn one-off execution into reusable capability, under controlled retention.**

## Lifecycle

![CapWeaver Capability Lifecycle](CoreCoder/nanocoder_tool_lifecycle.svg)

The current lifecycle is:

`tool_search / skill_search -> tool_forge -> ephemeral -> session / retained -> optional skillification -> persistent skill`

In practice, this means:

- reuse an existing retained tool or skill when retrieval hits
- forge a task-scoped tool only when retrieval misses
- run the current task first
- review the result afterward
- then discard it, keep it for the current session, retain it as a persistent tool, or package the workflow as a reusable skill

## Core Idea

| Stage | What happens |
|---|---|
| `tool_search / skill_search` | Reuse a retained tool or workflow skill first |
| `tool_forge` | Generate a new tool only when retrieval misses |
| `ephemeral` | Register the tool for the current task |
| `session` | Keep it available during the current running session |
| `retained` | Save the executable tool into `tool_store` |
| `skillification` | Package a retained tool or reusable workflow as a skill |
| `persistent skill` | Save the workflow capability into `skill_store` |

## What Changed in v0.2

| Area | v0.1 | v0.2 |
|---|---|---|
| Persistence | Mainly `session -> skill` | `session -> retained` and optional `skillification` |
| Reuse search | Skill-centric | Separate `tool_search` and `skill_search` |
| Skill creation | Mostly tool-backed | Tool-backed and workflow-first |
| Visibility | Basic lifecycle | Capability telemetry and stats |
| Runtime commands | `/tools`, `/skills` | `/tools`, `/retained`, `/skills`, `/capstats` |

## Repository Structure

```text
.
├─ CoreCoder/
│  ├─ corecoder/
│  ├─ tests/
│  ├─ README.md
│  ├─ README_CN.md
│  └─ pyproject.toml
├─ run_local_corecoder.ps1
├─ README.md
└─ README_CN.md
```

The main code lives under `CoreCoder/`.

## Quick Start

Use your own environment variables or a local `.env` file:

```powershell
$env:OPENAI_API_KEY="your-api-key"
$env:OPENAI_BASE_URL="https://your-openai-compatible-endpoint/v1"
./run_local_corecoder.ps1 -Model "your-model-name"
```

Or run directly from the package directory:

```powershell
cd CoreCoder
python -m corecoder -m your-model-name
```

## Common Commands

```text
/help       Show help
/tools      List currently loaded tools
/retained   List saved retained tools
/skills     List saved skills
/capstats   Show capability growth stats
/save       Save conversation history
/sessions   List saved sessions
/reset      Reset current conversation
```

## Attribution

This project is **based on and inspired by** [CoreCoder](https://github.com/he-yufeng/CoreCoder) by Yufeng He.

CapWeaver keeps the compact agent skeleton from CoreCoder and builds additional mechanisms for:

- retained-tool retrieval
- workflow skill retrieval
- runtime tool forging
- capability retention
- workflow skillification
- protected persistence

If you are interested in the original minimal architecture, please also read:

- `CoreCoder/README.md`
- `CoreCoder/README_CN.md`

## Notes

- `session` tools only live in the current running process.
- retained tools and workflow skills are stored separately.
- `/save` currently saves conversation history, not in-memory session tools.
- The runtime package name and CLI entry remain `corecoder` for compatibility with the upstream structure.

## License

MIT
