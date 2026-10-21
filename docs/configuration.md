# Configuration

[Default configuration](defaults.md) covers the seeded shell, Git, tmux, Vim, EditorConfig and agent settings. Existing user files are preserved.

## AGENTS.md

You keep one instruction file, `~/.agentainer/AGENTS.md`, and every agent reads it:

| Agent | Reads | How |
|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md` | Contains `@~/.agentainer/AGENTS.md` ([imports](https://code.claude.com/docs/en/memory)) |
| Codex | `~/.codex/AGENTS.md` | Symlink |
| Antigravity | `~/.gemini/AGENTS.md` | Symlink |
| OpenCode | `~/.config/opencode/AGENTS.md` | Symlink |

Claude Code is set to load both `CLAUDE.md` and `AGENTS.md` in a repo that has both ([instruction files setting](https://code.claude.com/docs/en/memory)). Each repo's own `AGENTS.md` still loads on top of yours. If a link path already holds a file of your own, the entrypoint leaves it and prints a warning.

The first start copies the image's default. When an image's default differs from your file:

- The entrypoint replaces the file with the image's default only when all of these hold: you never edited the file (it still matches a default this home has seen), the image has a valid release version, and that version is newer than every recorded version that shipped the file's current content. A prerelease can update an older prerelease default but never a default associated with a stable release. It keeps the file mode and prints one line saying so. Release versions follow [SemVer](https://semver.org/), including dated development builds such as `0.1.0-dev.20261019.1`. The image sets the version in `AGENTAINER_IMAGE_VERSION`.
- In every other case the file is not touched: you edited it, the image is older (for example another container on the same home volume runs an older image), the image is a prerelease and your default is associated with a stable release, or the image is a local build (`dev`). If the image's default is one this home has not seen before, the entrypoint prints one notice, and `agentainer-agents diff` shows the difference.
- A symlinked `~/.agentainer/AGENTS.md`, for example from a dotfiles repo, is never replaced.

`~/.agentainer/agents-default.sha256` lists every default the home has seen, one line per default and image version: `<sha256> <version>`. A line with only a hash comes from an image that did not record its version and counts as older than any release. So an older image never rolls the file back, and two images that share one home volume do not report each other's default more than once.

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
| Claude Code | `mcpServers` in `~/.claude.json`, or `$CLAUDE_CONFIG_DIR/.claude.json` |
| Codex | A marked block in `~/.codex/config.toml` |
| Antigravity | `mcpServers` in `~/.gemini/config/mcp_config.json` |
| OpenCode | `mcp.servers` in `~/.config/opencode/opencode.json` |

The JSON paths and formats match output from `claude mcp add-json --scope user` and `agy mcp add`, checked in the image. Claude documents its [user scope](https://code.claude.com/docs/en/mcp).

The entrypoint runs the sync when `mcp.json` changes, and `agentainer-mcp list` shows what it manages. It adds, updates and removes only the servers it added and never touches servers you added yourself. Deleting `mcp.json` removes the servers it added. Config files that are symlinks stay symlinks; the sync writes the file the link points to. Direct syncs and startup syncs share one lock, so they run one at a time on a shared home volume. Startup uses `agentainer-mcp sync --if-changed`, which checks and records the input hash under that same lock; a direct `agentainer-mcp sync` runs even when the input has not changed. Failed writes leave no success stamp and retry on the next start. A journal records config hashes and managed names before each write, so a restart can recover ownership after an interrupted sync. If the config changed independently during that interruption, sync stops for inspection rather than claiming ownership.

Server names may use only letters, digits, `-` and `_`. Any other name stops the sync with an error such as `agentainer-mcp: server name 'my.server' may only use letters, digits, - and _; nothing changed`.

A server entry has these keys:

| Kind | Keys | `type` |
|---|---|---|
| Command | `command`, `args`, `env` | `stdio` (optional) |
| URL | `url`, `headers` | `http` (default) or `sse` |

Any other `type` stops the sync with an error and changes nothing. Other keys, such as `cwd`, `timeout` or `disabled`, are not passed on; the sync prints a warning naming them.

Limits per agent:

- SSE servers reach Claude Code as SSE. Codex supports only streamable HTTP and Antigravity only `stdio` and `http`, so both leave an SSE server out with a warning. OpenCode gets it as a remote server, with a warning that this is not verified.
- Keep secrets as `${NAME}` references to variables in your env file; no agent config receives the value. The sync writes literal values directly into agent config files and never passes server configuration to a child process. New config files have mode `0600`; existing files keep their permissions.
- Antigravity has no documented syntax for variable references. For `agy`, the sync leaves out `env` entries that are `${NAME}` references (the server inherits the container's environment instead) and does not write headers that contain `${NAME}`, such as `Authorization: Bearer ${TOKEN}`. It prints a warning for each; add those headers in Antigravity by hand.
- Codex sends a `${NAME}` header variable as the whole header value. `Authorization: Bearer ${NAME}` works. For any other header written as `Bearer ${NAME}`, the sync leaves it out for Codex with a warning: store `Bearer <token>` in the variable and write the header value as `${NAME}`.
- Codex passes a server only the variables named in its config, under their own names. An `env` entry such as `API_KEY=${OTHER}` cannot rename a variable for Codex, so the sync leaves it out with a warning; give the variable the name the server expects.
- If `~/.config/opencode/opencode.jsonc` exists, the OpenCode sync stops with an error, because it edits only `opencode.json`.
- Re-syncing replaces the servers it manages, so settings you change inside an agent for one of them may not survive.

In a hand check, Codex and Antigravity listed a synced server's tools, and `claude mcp list` reported the server as connected. OpenCode is not verified: `opencode mcp list` prints "No MCP servers configured" even for a server that `opencode mcp add` wrote itself.

## Tools that agents install

`AGENTAINER_TOOLS` decides where `npm -g`, `cargo install`, `go install`, `uv tool` and `pipx` put things:

| Value | Location | Survives a new container |
|---|---|---|
| `ephemeral` (default) | `/var/lib/agentainer/tools` | No |
| `persist` | `~/.agentainer/tools` | Yes |

Image tools come first on `PATH`, so an installed tool never hides an image tool. When the image changes and persisted tools exist, the entrypoint warns; `agentainer-tools reset` moves them to a dated backup. Resets share a lock and reserve unique backup paths across containers. `agentainer-tools status` shows the mode and what is installed.

Ubuntu's Python refuses `pip install` outside a virtual environment, `pip install --user` included (PEP 668), so use `uv`, `pipx` or a venv. `PYTHONUSERBASE` points into the same tools root, but plain `pip` never installs there.

The image has `ansible-core` (`ansible`, `ansible-playbook`, `ansible-galaxy` and the other commands) without the community collections. Install the ones you use with `ansible-galaxy collection install community.general`. They go to `~/.ansible/collections` on the home volume.

## OpenRouter

| Command | What it does |
|---|---|
| `openrouter-claude` | Runs `claude` against `https://openrouter.ai/api` with `OPENROUTER_API_KEY`, for that process only ([OpenRouter guide](https://openrouter.ai/docs/cookbook/coding-agents/claude-code-integration)). It also sets `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`, which turns on the gateway model picker, unless you set it yourself. |
| `openrouter-codex` | Runs `codex` with an `openrouter` provider and the model `~openai/gpt-sol-latest`. `-m` picks another model ([OpenRouter guide](https://openrouter.ai/docs/cookbook/coding-agents/codex-cli)). |
| `opencode` | Built-in provider. Set `OPENROUTER_API_KEY` and use the full OpenRouter model ID after the `openrouter/` prefix, such as `openrouter/<vendor>/<model>` ([OpenCode providers](https://opencode.ai/v2/docs/providers)). |

The key reaches OpenRouter as a bearer token and appears in no argument list, log or file. Antigravity has no OpenRouter support.

Limits: Anthropic "doesn't support routing Claude Code to non-Claude models through any gateway" ([LLM gateway](https://code.claude.com/docs/en/llm-gateway)). Codex accepts only `wire_api = "responses"`, so the endpoint must serve the OpenAI Responses API ([Codex config reference](https://learn.chatgpt.com/docs/config-file/config-reference)).

## Startup messages

The entrypoint prints its messages on stderr, each starting with `agentainer:`. `AGENTAINER_QUIET=1` hides the line that lists which credential variables are set. Warnings and every other message still print.

If you do not set `AGENTAINER_QUIET`, the entrypoint sets it to `1` for a one-shot command, such as `podman run --rm IMAGE claude --version`, and to `0` for the default command, `sleep infinity`. Set `AGENTAINER_QUIET=0` to see the line for a one-shot command, or `AGENTAINER_QUIET=1` to hide it for a long-running container.
