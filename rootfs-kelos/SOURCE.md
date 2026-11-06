# Kelos files in this directory

Source: https://github.com/kelos-dev/kelos, tag v0.62.0, commit 8b0805c6474017c0347e2f4e658f7b15e8b143db. Apache-2.0, see LICENSE.kelos. Kelos v0.62.0 has no NOTICE file.

| File here | Source | Change |
|---|---|---|
| kelos_entrypoint_claude.sh | claude-code/kelos_entrypoint.sh | none |
| kelos_entrypoint_codex.sh | codex/kelos_entrypoint.sh | six marked changes: auth.json written only when missing, created with mode 0600, the config.toml setting added only when absent, every entry in CODEX_HOME except auth.json removed at each start (lost+found included on an ext4 volume), refusing when CODEX_HOME is not /home/kelos/.codex or is a symlink, or auth.json is a symlink or not a regular file, an existing auth.json replaced from CODEX_AUTH_JSON when it is not valid JSON, lacks the token fields, or holds another account or other credentials, and the MCP gateway tables appended to config.toml with the token passed to codex in its environment (AGENTAINER CHANGE, CHANGE 2, CHANGE 3, CHANGE 4, CHANGE 5, CHANGE 6) |
| agent-gh-wrapper.sh | hack/agent-gh-wrapper.sh | none |
| /kelos/kelos-capture (built in Containerfile.kelos) | Built from source from the chadmayfield/kelos fork (github.com/chadmayfield/kelos), branch proxy-env-for-git-init, commit ca909c7f6b80e9ac8ab7b8db11399e4363aa841d, on top of the v0.62.0 base commit. Not the upstream binary. | PR capture reads GitHub over REST instead of GraphQL (the egress proxy blocks GraphQL) |
| LICENSE.kelos | LICENSE | none |

kelos_entrypoint.sh (dispatcher), kelos_guard.sh, claude-wrapper.sh and mcp-headers.sh are not from Kelos. They are written for this image.

## MCP gateway

The image refuses Kelos's own MCP setting, `KELOS_MCP_SERVERS`: Kelos copies header values from a Secret into that variable in plain text, so they would sit in the pod spec. The image reads one MCP server from two files instead, mounted read-only at `/etc/agentainer/mcp` (for example from a Secret with the keys `url` and `token`):

| File | Rule, checked by the guard before any config file is written |
|---|---|
| `url` | One line, at most 512 bytes, matching `^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~/-]*)?$` |
| `token` | Matches `^[A-Za-z0-9._~+/=-]{16,4096}$` after one trailing newline is removed |

- The `url` file is the switch. With neither file, no MCP server is configured and the image behaves as before. That includes the empty directory Kubernetes mounts for a missing `optional` Secret.
- With only one of the two files, the pod refuses to start (exit 78).
- A value that breaks its rule is refused with the file's name and never its content. This keeps a quote, backslash, newline or space out of the JSON and TOML that the entrypoints write.
- `AGENTAINER_MCP_TOKEN` set in the pod environment is refused, so the token cannot be put in the pod spec.
- The server is named `gateway`, so Claude's tool names are `mcp__gateway__<tool>`.

Claude: the wrapper writes `~/.claude/mcp-gateway.json` with the URL and `headersHelper` `/usr/local/lib/kelos/mcp-headers`, then passes `--mcp-config` with that file. `--strict-mcp-config` stays, so no other MCP configuration is read. Claude removes credential-like variables from a helper's environment, so the helper reads the token file and prints `{"Authorization":"Bearer <token>"}`. The token is not in the config file, in argv or in claude's environment.

Codex: the entrypoint appends `[mcp_servers.gateway]` with the URL and `bearer_token_env_var = "AGENTAINER_MCP_TOKEN"`, and `[shell_environment_policy.filters]` with `"AGENTAINER_MCP_*" = "exclude"`, after every other write to `config.toml`. It sets `AGENTAINER_MCP_TOKEN` from the file with an assignment prefix on the `codex exec` line, so only that codex process has it. The shell policy removes it from the commands the agent runs.

The agent's shell runs as the same user as the CLI, so it can read the token file, and under Codex the CLI's process environment. These steps keep the token out of the pod spec, argv, the environment of the agent's commands, and the logs. They do not hide it from the agent.

Build: the `kelos-capture` stage of Containerfile.kelos fetches that commit by full SHA (and checks `git rev-parse HEAD` against it), then runs `CGO_ENABLED=0 GOOS=linux GOARCH=$TARGETARCH go build -trimpath -ldflags "-X github.com/kelos-dev/kelos/internal/version.Version=v0.62.0-proxy.3" -o /out/kelos-capture ./cmd/kelos-capture` with golang 1.25.14, pinned by index digest in the Containerfile. The fork's go.mod says `go 1.25.0` and has no toolchain line.

Two builds of the same commit gave these SHA-256 values for the binary inside the image:

    8a368760f40ed99552ce441198fde9c640d010110203a13a0ac64c315a94804b  linux/amd64
    0daa73988ea31da678736ca92702ea6ca7efcb4ed10076eb96a6f1e6ef3e0c2a  linux/arm64
