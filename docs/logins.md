# Signing in

Put API keys and tokens in the env file (`~/.config/agentainer/env`, mode 600; see [env.example](../env.example)). Subscription logins happen inside the container and are stored in the home volume, so they survive a new container.

| Agent | Subscription login without a local browser | API key | Stored in |
|---|---|---|---|
| Claude Code | Run `claude setup-token` on a machine with a browser and set `CLAUDE_CODE_OAUTH_TOKEN`. Or run `/login` in the container and paste the code. | `ANTHROPIC_API_KEY` | `~/.claude/.credentials.json` |
| Codex | `codex login --device-auth`. Turn on device code login in your ChatGPT security settings first. | `printenv OPENAI_API_KEY \| codex login --with-api-key` | `~/.codex/auth.json` |
| Antigravity | Run `agy` and sign in. It offers the paste-code flow in a container. | `GEMINI_API_KEY` plus `"modelProvider": "gemini"` in its settings | `~/.gemini/antigravity-cli/antigravity-oauth-token` |
| OpenCode | `opencode auth login` | Provider variables such as `OPENROUTER_API_KEY` | `~/.local/share/opencode/opencode.db` |
| GitHub | n/a | `GH_TOKEN` (a fine-grained token) | `~/.config/gh/` |

Sources: [Claude authentication](https://code.claude.com/docs/en/authentication), [Codex auth](https://learn.chatgpt.com/docs/auth), [Antigravity install](https://antigravity.google/docs/cli/install.md), OpenCode v2 docs (`cli/providers.mdx`).

## Which Claude login wins

Claude Code uses the first one it finds in this order: `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, then a `/login` session ([authentication precedence](https://code.claude.com/docs/en/authentication)). An `ANTHROPIC_API_KEY` in the env file therefore bills the API even if you signed in with a subscription. Claude asks once in interactive mode before it uses that key.

## GitHub and git

When `GH_TOKEN` or `GITHUB_TOKEN` is set, the entrypoint runs `gh auth setup-git`, so `git push` over HTTPS uses the token. It skips the step when this container's `gh` is already the credential helper, so containers sharing a home volume do not rewrite `~/.gitconfig` on every start.

`GIT_AUTHOR_NAME` and `GIT_AUTHOR_EMAIL` set your git identity when `~/.gitconfig` has none. If they later differ from the configured identity, git uses them as the author and the configured identity as the committer, and the entrypoint prints a warning.

## Credential exposure

Every variable in the env file is readable by every process in the container: all four agents, the tools they run, and MCP servers. Pass only the keys you need, and prefer narrowly scoped tokens. See [docs/security.md](security.md).
