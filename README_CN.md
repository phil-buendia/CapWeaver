# CapWeaver

CapWeaver 是一个围绕**能力增长**来设计的轻量级 Coding Agent 项目。

它以 [CoreCoder](https://github.com/he-yufeng/CoreCoder) 的极简架构为基础，在上面补了一条更完整的能力生命周期：

- 先检索已有 skill
- 缺能力时动态生成临时 tool
- 在当前任务中使用
- 任务结束后再决定丢弃、保留到当前会话，还是升级为长期 skill

当前公开版本：**v0.1.0**

## 这个项目想解决什么

很多 Coding Agent 能把一次任务做完，但很难把这次执行过程沉淀成后续可复用的能力。CapWeaver 想探索的是一条更务实的路线：

**把一次性执行，变成受控的能力形成过程。**

## 生命周期

![CapWeaver Capability Lifecycle](CoreCoder/nanocoder_tool_lifecycle.svg)

当前主流程可以概括为：

`skill_search -> tool_forge -> ephemeral tool -> session tool / persistent skill / discard`

## 核心思路

| 阶段 | 作用 |
|---|---|
| `skill_search` | 优先复用已有 skill |
| `tool_forge` | 检索失败时再生成新工具 |
| `ephemeral tool` | 当前任务可用的临时工具 |
| `session tool` | 当前运行会话内可继续复用 |
| `persistent skill` | 写入 `skill_store`，跨会话长期复用 |

## CapWeaver 和 CoreCoder 的区别

| 维度 | CoreCoder | CapWeaver |
|---|---|---|
| 项目定位 | 极简 Coding Agent 骨架 | 面向能力增长的 Agent 原型 |
| 工具体系 | 以静态工具集为主 | 支持运行时动态注册 |
| 复用路径 | 偏固定 | 先检索、再决定是否生成 |
| 新能力生成 | 不是主线 | 支持 `tool_forge` 动态造工具 |
| 任务后处理 | 没有完整生命周期 | `ephemeral -> session -> skill` |
| skill 落盘 | 较弱 | 受控持久化与保护目录 |

## 仓库结构

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

主要代码位于 `CoreCoder/` 目录下。

## 快速开始

你可以使用本地环境变量，或者自己维护一个本地 `.env`：

```powershell
$env:OPENAI_API_KEY="your-api-key"
$env:OPENAI_BASE_URL="https://your-openai-compatible-endpoint/v1"
./run_local_corecoder.ps1 -Model "your-model-name"
```

或者进入包目录直接运行：

```powershell
cd CoreCoder
python -m corecoder -m your-model-name
```

## 常用命令

```text
/help       查看帮助
/tools      查看当前已加载工具
/skills     查看已保存 skill
/save       保存会话历史
/sessions   查看已保存会话
/reset      重置当前对话
```

## 引用与致谢

这个项目**基于并参考了** [CoreCoder](https://github.com/he-yufeng/CoreCoder)。

CapWeaver 保留了 CoreCoder 作为极简 Agent 骨架的核心价值，并在其基础上继续扩展了：

- skill 检索
- 动态 tool forging
- 能力留存决策
- 受保护的 skill 持久化

如果你想先理解原始极简架构，可以优先阅读：

- `CoreCoder/README.md`
- `CoreCoder/README_CN.md`

## 说明

- `session tool` 只在当前运行进程里有效。
- `/save` 目前保存的是对话历史，不会把内存中的 session tool 一起持久化。
- 为了兼容上游结构，当前运行时包名和 CLI 入口仍然保留为 `corecoder`。

## License

MIT。
