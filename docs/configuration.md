# Configuration

## AGENTS.md

You keep one instruction file, `~/.agentainer/AGENTS.md`, and every agent reads it:

| Agent | Reads | How |
|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md` | Contains `@~/.agentainer/AGENTS.md` ([imports](https://code.claude.com/docs/en/memory)) |
| Codex | `~/.codex/AGENTS.md` | Symlink |
| Antigravity | `~/.gemini/AGENTS.md` | Symlink |
| OpenCode | `~/.config/opencode/AGENTS.md` | Symlink |

Claude Code is set to load both `CLAUDE.md` and `AGENTS.md` in a repo that has both ([instruction files setting](https://code.claude.com/docs/en/memory)). Each repo's own `AGENTS.md` still loads on top of yours. If a link path already holds a file of your own, the entrypoint leaves it and prints a warning.

The first start copies the image's default. When a later image ships a different default:

- If you never edited the file (it still matches a default this home has seen), the entrypoint replaces it with the new default, keeps its file mode, and prints one line saying so.
- If you edited it, the file is never touched. The entrypoint prints one notice, and `agentainer-agents diff` shows the difference.
- A symlinked `~/.agentainer/AGENTS.md`, for example from a dotfiles repo, is never replaced.

`~/.agentainer/agents-default.sha256` lists every default the home has seen, so two images that share one home volume do not report each other's default.

## MCP servers

Define servers once in `~/.agentainer/mcp.json`, in the `mcpServers` format most MCP server READMEs use:

```json
{"mcpServers": {
  "remote": {"url": "https://mcp.example.com/mcp", "headers": {"Authorization": "Bearer ${EXAMPLE_TOKEN}"}},
  "everything": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-everything"]}
}}
```

`agentainer-mcp sync` writes them into each agent's own configuration:

| Agent | Where |
|---|---|
| Claude Code | `claude mcp add-json --scope user` |
| Codex | A marked block in `~/.codex/config.toml` |
| Antigravity | `agy mcp add` |
| OpenCode | `mcp.servers` in `~/.config/opencode/opencode.json` |

The entrypoint runs the sync when `mcp.json` changes, and `agentainer-mcp list` shows what it manages. It adds, updates and removes only the servers it added and never touches servers you added yourself. Deleting `mcp.json` removes the servers it added. Config files that are symlinks stay symlinks; the sync writes the file the link points to. When containers sharing a home volume start at once, their syncs run one at a time.

A server entry has these keys:

| Kind | Keys | `type` |
|---|---|---|
| Command | `command`, `args`, `env` | `stdio` (optional) |
| URL | `url`, `headers` | `http` (default) or `sse` |

Any other `type` stops the sync with an error and changes nothing. Other keys, such as `cwd`, `timeout` or `disabled`, are not passed on; the sync prints a warning naming them.

Limits per agent:

- SSE servers reach Claude Code as SSE. Codex supports only streamable HTTP and Antigravity only `stdio` and `http`, so both leave an SSE server out with a warning. OpenCode gets it as a remote server, with a warning that this is not verified.
- Keep secrets as `${NAME}` references to variables in your env file; no agent config receives the value. Literal values reach `claude` and `agy` on their command line, where `ps` can show them for a moment.
- Antigravity has no documented syntax for variable references. For `agy`, the sync leaves out `env` entries that are `${NAME}` references (the server inherits the container's environment instead) and does not write headers that contain `${NAME}`, such as `Authorization: Bearer ${TOKEN}`. It prints a warning for each; add those headers in Antigravity by hand.
- Codex sends a `${NAME}` header variable as the whole header value. `Authorization: Bearer ${NAME}` works. For any other header written as `Bearer ${NAME}`, the sync leaves it out for Codex with a warning: store `Bearer <token>` in the variable and write the header value as `${NAME}`.
- Re-syncing replaces the servers it manages, so settings you change inside an agent for one of them may not survive.

In a hand check, Codex and Antigravity listed a synced server's tools, and `claude mcp list` reported the server as connected. OpenCode is not verified: `opencode mcp list` prints "No MCP servers configured" even for a server that `opencode mcp add` wrote itself.

## Tools that agents install

`AGENTAINER_TOOLS` decides where `npm -g`, `cargo install`, `go install`, `uv tool`, `pipx` and `pip --user` put things:

| Value | Location | Survives a new container |
|---|---|---|
| `ephemeral` (default) | `/var/lib/agentainer/tools` | No |
| `persist` | `~/.agentainer/tools` | Yes |

Image tools come first on `PATH`, so an installed tool never hides an image tool. When the image changes and persisted tools exist, the entrypoint warns; `agentainer-tools reset` moves them to a dated backup. `agentainer-tools status` shows the mode and what is installed.

Ubuntu's Python refuses `pip install` outside a virtual environment (PEP 668), so use `uv`, `pipx` or a venv.

The image has `ansible-core` (`ansible`, `ansible-playbook`, `ansible-galaxy` and the other commands) without the community collections. Install the ones you use with `ansible-galaxy collection install community.general`. They go to `~/.ansible/collections` on the home volume.

## OpenRouter

| Command | What it does |
|---|---|
| `openrouter-claude` | Runs `claude` against `https://openrouter.ai/api` with `OPENROUTER_API_KEY`, for that process only ([OpenRouter guide](https://openrouter.ai/docs/cookbook/coding-agents/claude-code-integration)). It also sets `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`, which turns on the gateway model picker, unless you set it yourself. |
| `openrouter-codex` | Runs `codex` with an `openrouter` provider and the model `~openai/gpt-sol-latest`. `-m` picks another model ([OpenRouter guide](https://openrouter.ai/docs/cookbook/coding-agents/codex-cli)). |
| `opencode` | Built-in provider. Set `OPENROUTER_API_KEY` and use models such as `openrouter/<vendor>/<model>`. |

The key reaches OpenRouter as a bearer token and appears in no argument list, log or file. Antigravity has no OpenRouter support.

Limits: Anthropic "doesn't support routing Claude Code to non-Claude models through any gateway" ([LLM gateway](https://code.claude.com/docs/en/llm-gateway)). Codex accepts only `wire_api = "responses"`, so the endpoint must serve the OpenAI Responses API ([Codex config reference](https://learn.chatgpt.com/docs/config-file/config-reference)).
