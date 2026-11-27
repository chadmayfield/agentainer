# Kelos files in this directory

Source: https://github.com/kelos-dev/kelos, tag v0.62.0, commit 8b0805c6474017c0347e2f4e658f7b15e8b143db. Apache-2.0, see LICENSE.kelos. Kelos v0.62.0 has no NOTICE file.

| File here | Source | Change |
|---|---|---|
| kelos_entrypoint_claude.sh | claude-code/kelos_entrypoint.sh | none |
| kelos_entrypoint_codex.sh | codex/kelos_entrypoint.sh | seven marked changes (AGENTAINER CHANGE, CHANGE 2 to CHANGE 7), listed below |
| agent-gh-wrapper.sh | hack/agent-gh-wrapper.sh | none |
| /kelos/kelos-capture (built in Containerfile.kelos) | Built from source from a `v<version>-rest.<n>` tag of the fork at github.com/chadmayfield/kelos, not the upstream binary. | Lists pull requests over the GitHub REST API instead of GraphQL; see below |
| LICENSE.kelos | LICENSE | none |

kelos_entrypoint.sh (dispatcher), kelos_guard.sh, claude-wrapper.sh and mcp-headers.sh are not from Kelos. They are written for this image.

The changes in kelos_entrypoint_codex.sh:

| Marker | Change |
|---|---|
| AGENTAINER CHANGE | auth.json is written only when it is missing |
| CHANGE 2 | auth.json is created with mode 0600 |
| CHANGE 3 | every entry in CODEX_HOME except auth.json and the lock file is removed at each start (lost+found included on an ext4 volume), under an exclusive flock that the run holds until it ends; only the script and codex keep the lock's file descriptor (node, codex login status and kelos-capture run with it closed), and a lock file without owner read or write gets them back; the start is refused when CODEX_HOME is not /home/kelos/.codex or is a symlink, or auth.json is a symlink or not a regular file, checked before and again after the lock is taken |
| CHANGE 4 | an existing auth.json is replaced from CODEX_AUTH_JSON when it is not valid JSON, lacks the token fields, holds another account (tokens.account_id or the account in the id_token), another user, other credentials, or names no account that can be compared |
| CHANGE 5 | the MCP gateway tables are appended to config.toml, and the token is passed to codex in its environment |
| CHANGE 6 | the script exits with kelos-capture's status when codex succeeded |
| CHANGE 7 | CODEX_AUTH_JSON is removed from the environment once auth.json is written, so the setup command, codex and the commands the agent runs do not get it |

## kelos-capture

The fork at github.com/chadmayfield/kelos carries tags named `v<upstream version>-rest.<n>`, for example `v0.65.0-rest.1`. Each is upstream kelos-dev/kelos at release `v<upstream version>` plus one commit: kelos-capture lists pull requests with `gh api repos/<owner>/<repo>/pulls` (REST) instead of `gh pr list` (GraphQL). Upstream kelos-capture uses GraphQL, which some HTTP egress proxies block while they allow the REST API.

`scripts/bump_versions.py` (r_kelos) picks the highest such tag, by version and then by `n`, that is at least 72 hours old (docs/kelos.md, Pins). It pins the commit the tag points to, after peeling an annotated tag, as `KELOS_FORK_COMMIT` and the tag name as `KELOS_CAPTURE_VERSION` in Containerfile.kelos. Before it writes them, it checks that the tag's claude-code/kelos_entrypoint.sh, hack/agent-gh-wrapper.sh and LICENSE are the files in this directory, and that its codex/kelos_entrypoint.sh is still the v0.62.0 file the Codex entrypoint here starts from. A Kelos release that changes one of them stops the update until the copies here follow it.

Build: the `kelos-capture` stage of Containerfile.kelos fetches `KELOS_FORK_COMMIT` by full SHA (and checks `git rev-parse HEAD` against it), then runs `CGO_ENABLED=0 GOOS=linux GOARCH=$TARGETARCH go build -trimpath -ldflags "-X github.com/kelos-dev/kelos/internal/version.Version=$KELOS_CAPTURE_VERSION" -o /out/kelos-capture ./cmd/kelos-capture` in the golang image pinned as `GOLANG_IMAGE`.

To build the upstream code instead, change the remote in that stage to https://github.com/kelos-dev/kelos.git and set `KELOS_FORK_COMMIT` and `KELOS_CAPTURE_VERSION` to an upstream release's commit and tag. kelos-capture then uses GraphQL again.

## MCP gateway

The image refuses Kelos's own MCP setting, `KELOS_MCP_SERVERS`: Kelos copies header values from a Secret into that variable in plain text, so they would sit in the pod spec. The image reads one MCP server from two files instead, mounted read-only at `/etc/agentainer/mcp` (for example from a Secret with the keys `url` and `token`):

| File | Rule, checked by the guard before any config file is written |
|---|---|
| `url` | One line, at most 512 bytes, matching `^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~/-]*)?$` |
| `token` | Matches `^[A-Za-z0-9._~+/=-]{16,4096}$` after one trailing newline is removed |

- The `url` file is the switch. With neither file, no MCP server is configured. That includes the empty directory Kubernetes mounts for a missing `optional` Secret.
- With only one of the two files, the pod refuses to start (exit 78).
- A value that breaks its rule is refused with the file's name and never its content. This keeps a quote, backslash, newline or space out of the JSON and TOML that the entrypoints write.
- `AGENTAINER_MCP_TOKEN` set in the pod environment is refused, so the token cannot be put in the pod spec.
- The server is named `gateway`, so Claude's tool names are `mcp__gateway__<tool>`.

Claude: the wrapper writes `~/.claude/mcp-gateway.json` with the URL and `headersHelper` `/usr/local/lib/kelos/mcp-headers`, then passes `--mcp-config` with that file. `--strict-mcp-config` stays, so no other MCP configuration is read. Claude removes credential-like variables from a helper's environment, so the helper reads the token file and prints `{"Authorization":"Bearer <token>"}`. The token is not in the config file, in argv or in claude's environment.

Codex: the entrypoint appends `[mcp_servers.gateway]` with the URL and `bearer_token_env_var = "AGENTAINER_MCP_TOKEN"`, and `[shell_environment_policy.filters]` with `"AGENTAINER_MCP_*" = "exclude"`, after every other write to `config.toml`. It sets `AGENTAINER_MCP_TOKEN` from the file with an assignment prefix on the `codex exec` line, so only that codex process has it. The shell policy removes it from the commands the agent runs; the tests check that config.toml holds the policy, not that Codex applies it.

The agent's shell runs as the same user as the CLI, so it can read the token file, and under Codex the CLI's process environment. These steps keep the token out of the pod spec, argv, the environment of the agent's commands, and the logs. They do not hide it from the agent.
