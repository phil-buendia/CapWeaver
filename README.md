# CapWeaver

CapWeaver is a lightweight coding agent project focused on **capability growth**.

It starts from the compact architecture of [CoreCoder](https://github.com/he-yufeng/CoreCoder), and extends it with a controlled capability lifecycle:

- search existing skills first
- forge a temporary tool when needed
- use it in the current task
- decide whether to discard it, keep it for the current session, or promote it into a persistent skill

Current public release: **v0.1.0**

## Why This Project

Most coding agents can finish a task, but they do not naturally get better at similar tasks over time. CapWeaver explores a small but practical direction:

**turn one-off execution into reusable capability, under explicit control.**

That is the core idea behind this repository.

## Lifecycle

![CapWeaver Capability Lifecycle](CoreCoder/nanocoder_tool_lifecycle.svg)

The current lifecycle is:

`skill_search -> tool_forge -> ephemeral tool -> session tool / persistent skill / discard`

## Core Idea

| Stage | What happens |
|---|---|
| `skill_search` | Try to reuse an existing skill first |
| `tool_forge` | Generate a new tool only when retrieval misses |
| `ephemeral tool` | Register the tool for the current task |
| `session tool` | Keep it available during the current running session |
| `persistent skill` | Save it into `skill_store` for reuse across sessions |

## CapWeaver vs CoreCoder

| Aspect | CoreCoder | CapWeaver |
|---|---|---|
| Project goal | Minimal coding agent blueprint | Capability-aware coding agent prototype |
| Tool system | Mostly static tool set | Dynamic runtime tool registration |
| Reuse path | Manual / fixed | Retrieval before generation |
| New capability creation | Not the main focus | `tool_forge` can generate tools on demand |
| Post-task handling | No capability lifecycle | `ephemeral -> session -> skill` |
| Skill persistence | Limited | Controlled retention and protected `skill_store` |

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
/skills     List saved skills
/save       Save conversation history
/sessions   List saved sessions
/reset      Reset current conversation
```

## Attribution

This project is **based on and inspired by** [CoreCoder](https://github.com/he-yufeng/CoreCoder) by Yufeng He.

CapWeaver keeps the compact agent skeleton from CoreCoder and builds additional mechanisms for:

- skill retrieval
- runtime tool forging
- capability retention
- protected skill persistence

If you are interested in the original minimal architecture, please also read:

- `CoreCoder/README.md`
- `CoreCoder/README_CN.md`

## Notes

- `session tool` only lives in the current running process.
- `/save` currently saves conversation history, not in-memory session tools.
- The runtime package name and CLI entry remain `corecoder` for compatibility with the upstream code structure.

## License

MIT.
