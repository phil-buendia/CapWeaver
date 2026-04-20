# CapWeaver

CapWeaver is a lightweight coding agent project built on top of [CoreCoder](https://github.com/he-yufeng/CoreCoder).

It keeps the small and readable architecture of the original project, but pushes it toward a more interesting direction: **capability growth**.

Instead of treating every task as a one-off execution, CapWeaver lets the agent:

1. search for an existing skill first
2. forge a temporary tool when no suitable skill is found
3. use that tool in the current task
4. decide whether it should be discarded, kept for the current session, or promoted into a persistent skill

Current public release: **v0.1.0**

## What CapWeaver Focuses On

Compared with the original CoreCoder, this project mainly explores three mechanisms:

1. **Skill retrieval before generation**
   The agent first checks whether an existing skill can solve the task.
2. **Dynamic tool forging**
   If no suitable skill is found, the agent can generate a new tool at runtime.
3. **Capability retention**
   A newly forged tool is not saved immediately. After the task finishes, it can be:
   - discarded
   - kept as a session tool
   - saved as a persistent skill

This makes the project less like a fixed tool runner, and more like a compact prototype for capability management.

## Lifecycle Overview

The current lifecycle is:

`skill_search -> tool_forge -> ephemeral tool -> session tool / persistent skill / discard`

In practice, this means:

- existing skills are reused first
- newly forged tools are task-scoped by default
- long-term persistence is explicit and controlled
- direct writes into `skill_store` are blocked unless they go through the managed flow

## Main Changes In CapWeaver

### 1. Dynamic tool registry
Tools are no longer treated as a fixed list at startup. The agent can register tools during runtime and rebuild its prompt around the updated capability set.

### 2. `skill_search`
A lightweight two-stage retrieval mechanism is used before creating a new capability:
- keyword overlap recall
- LLM reranking

### 3. `tool_forge`
If retrieval misses, the agent can ask the model to generate a new `Tool` subclass, validate it, and register it as an **ephemeral tool** for the current task.

### 4. Three-layer retention
A forged tool now has three possible destinations:
- **Ephemeral**: current task only
- **Session**: reusable in the current running session
- **Persistent**: saved into `skill_store` and reusable across future sessions

### 5. Protected skill storage
The repository now blocks direct writes to `corecoder/skill_store` through general tools such as `bash`, `write_file`, and `edit_file`. Reusable skills must go through the controlled path.

## Repository Layout

```text
CoreCoder/
  corecoder/
    agent.py
    cli.py
    context.py
    llm.py
    prompt.py
    session.py
    skill_library.py
    skill_manager.py
    skill_store/
    tools/
  tests/
  README.md
  README_CN.md
  pyproject.toml
```

## Run Locally

From the repository root:

```powershell
$env:OPENAI_API_KEY="your-api-key"
$env:OPENAI_BASE_URL="https://your-openai-compatible-endpoint/v1"
./run_local_corecoder.ps1 -Model "your-model-name"
```

Or run from the package directory:

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

## Notes

- `session tool` is only available in the current running process.
- `/save` currently saves conversation history, not in-memory session tools.
- The package name and CLI entry are still `corecoder` for compatibility with the upstream structure.

## Documentation

- Chinese README: `README_CN.md`
- Presentation material is included in the repository.

## License

MIT.
