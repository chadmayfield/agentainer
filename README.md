# Agentainer

Agentainer is one container image with four AI coding agents and a shared set of developer tools. You run it in a terminal on a laptop, a server or a Kubernetes cluster.

- Agents: [Claude Code](https://code.claude.com/docs/en/setup), [Codex CLI](https://github.com/openai/codex), [Antigravity CLI](https://antigravity.google/docs/cli/overview.md) (`agy`) and [OpenCode v2](https://opencode.ai/v2/docs).
- Base: Ubuntu 26.04 LTS, pinned by digest, with apt packages from the [Ubuntu snapshot service](https://documentation.ubuntu.com/server/how-to/software/snapshot-service/) at a pinned date.
- Tools: git, gh, Go, Rust, Python with uv and pipx, Node.js, ripgrep, jq, yq, shellcheck, trivy and more. `/etc/agentainer/versions.json` in the image lists every version.
- Platforms: `linux/amd64` and `linux/arm64`.

It has two goals. Agents see only what you mount and the credentials you pass in. The same image and tools run everywhere.

## Quick start

You need Podman or Docker. The launcher in `bin/agentainer` is a POSIX shell script.

```sh
mkdir -p ~/.config/agentainer
cp env.example ~/.config/agentainer/env
chmod 600 ~/.config/agentainer/env      # then fill in the keys you use
bin/agentainer up ~/code                 # ~/code becomes /workspace
bin/agentainer attach                    # tmux session "main"
```

Start an agent in a tmux window (`claude`, `codex`, `agy` or `opencode`). Close the terminal whenever you like. `bin/agentainer attach` brings you back to the same session with the agents still running (`tests/95-disconnect.sh`).

| Command | What it does |
|---|---|
| `agentainer up [--name N] [--sudo] [--image I] [DIR]` | Starts a detached container. DIR defaults to the current directory. |
| `agentainer attach [N]` | Runs `tmux new-session -A -s main` in the container |
| `agentainer shell [N]` | Opens a login shell |
| `agentainer down [N]` | Removes the container. The home volume stays. |
| `agentainer status` | Lists agentainer containers |

The launcher uses Podman when it finds it, otherwise Docker. `AGENTAINER_RUNTIME`, `AGENTAINER_IMAGE`, `AGENTAINER_ENV_FILE` and `AGENTAINER_HOME_VOLUME` override its defaults. It prints each command before running it (`tests/host/test-launcher.sh`).

## Running without the launcher

```sh
docker run -d --name agentainer --hostname agentainer \
  --security-opt no-new-privileges=true \
  --sysctl "net.ipv4.ping_group_range=1000 1000" \
  -v agentainer-home:/home/agent \
  -v "$HOME/code:/workspace" -w /workspace \
  --env-file "$HOME/.config/agentainer/env" \
  ghcr.io/chadmayfield/agentainer:latest
docker exec -it agentainer tmux new-session -A -s main
```

With Podman, use the same commands and add `--userns=keep-id:uid=1000,gid=1000`. It maps your host user to the container user, so files in `/workspace` stay yours (`man podman-run`).

- The container runs `sleep infinity` under `tini` as PID 1. Sessions are `exec` calls into tmux.
- The whole home directory `/home/agent` is one volume. Logins, settings and `AGENTS.md` live there and survive a new container. All containers that use the same volume share logins, and two containers running the same agent write the same files.
- The `ping_group_range` sysctl lets `ping` work without the `NET_RAW` capability. It names only GID 1000, because with Podman's keep-id the GID map is not contiguous and a wider range breaks.
- sudo: the image has passwordless sudo, and `no-new-privileges=true` turns it off ([Docker reference](https://docs.docker.com/reference/cli/docker/container/run/)). `agentainer up --sudo` leaves that option out. With sudo on, an agent can change anything in the container, including the binaries and the update locks. Packages installed with `sudo apt install` are lost when the container is recreated. Under rootful Docker, container root is UID 0 on the host inside the container's namespaces.
- File ownership: under rootful Docker on Linux, files written to `/workspace` belong to UID 1000 on the host. If your UID is different, build your own image with `scripts/build.sh --uid "$(id -u)" --gid "$(id -g)"`, or use Podman or rootless Docker.
- SSH agent on a Linux host: add `-v "$SSH_AUTH_SOCK:/run/ssh-agent.sock" -e SSH_AUTH_SOCK=/run/ssh-agent.sock`. CI checks this on a Linux runner (`.github/workflows/build.yml`). On macOS the socket path depends on the runtime and is not verified. The default for git is `GH_TOKEN`, see below.
- SELinux hosts may need `:z` on volume mounts. Not verified.

## Logging in

Put API keys and tokens in the env file. Subscription logins happen inside the container and are stored in the home volume.

| Agent | Subscription login without a local browser | API key | Stored in |
|---|---|---|---|
| Claude Code | Run `claude setup-token` on a machine with a browser and set `CLAUDE_CODE_OAUTH_TOKEN`. Or run `/login` in the container and paste the code. | `ANTHROPIC_API_KEY` | `~/.claude/.credentials.json` |
| Codex | `codex login --device-auth`. Turn on device code login in your ChatGPT security settings first. | `printenv OPENAI_API_KEY \| codex login --with-api-key` | `~/.codex/auth.json` |
| Antigravity | Run `agy` and sign in with the paste-code flow. Not verified in a container yet. | `GEMINI_API_KEY` plus `"modelProvider": "gemini"` in its settings | not verified |
| OpenCode | `opencode auth login` | Provider variables such as `OPENROUTER_API_KEY` | `~/.local/share/opencode/opencode.db` |
| GitHub | n/a | `GH_TOKEN` (a fine-grained token) | `~/.config/gh/` |

Sources: [Claude authentication](https://code.claude.com/docs/en/authentication), [Codex auth](https://learn.chatgpt.com/docs/auth), [Antigravity install](https://antigravity.google/docs/cli/install.md), OpenCode v2 docs (`cli/providers.mdx`).

Which Claude login wins: Claude Code uses the first one it finds in this order: `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, then a `/login` session ([authentication precedence](https://code.claude.com/docs/en/authentication)). An `ANTHROPIC_API_KEY` in the env file therefore bills the API even if you logged in with a subscription. Claude asks once in interactive mode before it uses that key.

When `GH_TOKEN` or `GITHUB_TOKEN` is set, the entrypoint runs `gh auth setup-git`, so `git push` over HTTPS uses the token. `GIT_AUTHOR_NAME` and `GIT_AUTHOR_EMAIL` set your git identity when `~/.gitconfig` has none (`tests/70-git-creds.sh`).

## Shared configuration

### AGENTS.md

You keep one instruction file, `~/.agentainer/AGENTS.md`. The first start copies a default from the image. After that it is yours, and image upgrades never overwrite it. If a new image ships a different default, the entrypoint prints a notice and `agentainer-agents diff` shows the change.

| Agent | Reads | How |
|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md` | Contains `@~/.agentainer/AGENTS.md` ([imports](https://code.claude.com/docs/en/memory)) |
| Codex | `~/.codex/AGENTS.md` | Symlink |
| Antigravity | `~/.gemini/AGENTS.md` | Symlink |
| OpenCode | `~/.config/opencode/AGENTS.md` | Symlink |

`tests/60-agents-md.sh` checks the wiring and that Codex reads the symlinked file. Whether Antigravity and OpenCode follow the symlink is not verified yet. Claude Code is set to load both `CLAUDE.md` and `AGENTS.md` in a repo that has both ([instruction files setting](https://code.claude.com/docs/en/memory)). Each repo's own `AGENTS.md` still loads on top.

### MCP servers

Define servers once in `~/.agentainer/mcp.json`, in the `mcpServers` format most MCP server READMEs use:

```json
{"mcpServers": {
  "remote": {"url": "https://mcp.example.com/mcp", "headers": {"Authorization": "Bearer ${EXAMPLE_TOKEN}"}},
  "everything": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-everything"]}
}}
```

`agentainer-mcp sync` writes them into each agent's config, through `claude mcp` and `agy mcp` for those two, a marked block in `~/.codex/config.toml` for Codex, and `mcp.servers` in `~/.config/opencode/opencode.json` for OpenCode. The entrypoint runs it when `mcp.json` changes. It adds, updates and removes only the servers it added, and never touches servers you added yourself (`tests/80-mcp.sh`, `tests/unit/test_mcp_sync.py`). `agentainer-mcp list` shows what it manages.

Keep secrets as `${NAME}` references to variables in your env file. No agent config receives the value. Literal values reach `claude` and `agy` on their command line, where `ps` can show them for a moment. Re-syncing replaces managed servers, so settings you change inside an agent for a managed server may not survive.

### Tools that agents install

`AGENTAINER_TOOLS` decides where `npm -g`, `cargo install`, `go install`, `uv tool`, `pipx` and `pip --user` put things:

| Value | Location | Survives a new container |
|---|---|---|
| `ephemeral` (default) | `/var/lib/agentainer/tools` | No |
| `persist` | `~/.agentainer/tools` | Yes |

Image tools come first on `PATH`, so a persisted tool never hides an image tool. When the image changes and persisted tools exist, the entrypoint warns. `agentainer-tools reset` renames the folder to a dated backup (`tests/50-entrypoint.sh`). Ubuntu's Python refuses `pip install` outside a venv (PEP 668), so use `uv`, `pipx` or a venv.

## Kubernetes with ContainerSSH

`deploy/kubernetes/` has an example you apply with `kubectl apply -k`. You reach the agent pod over SSH through [ContainerSSH](https://containerssh.io/v0.6/) v0.6.0, and each login lands in the same tmux session.

- Namespace `agentainer`: a StatefulSet with one pod, `agentainer-0`, and two volumes, `home` (20 Gi) and `workspace` (50 Gi). It passes the [Restricted Pod Security Standard](https://kubernetes.io/docs/concepts/security/pod-security-standards/), mounts no service account token, and keeps sudo off.
- Namespace `containerssh`: the ContainerSSH server in [persistent mode](https://containerssh.io/v0.6/reference/kubernetes/#persistent-mode), and a small Python webhook that checks SSH public keys and tells ContainerSSH which pod to use.
- The ContainerSSH image on Docker Hub is amd64 only, so its Deployment runs on amd64 nodes. The agentainer pod runs on either architecture.

Create the Secrets, then apply:

```sh
kubectl create namespace agentainer
kubectl create namespace containerssh
kubectl -n agentainer create secret generic agentainer-credentials \
  --from-env-file="$HOME/.config/agentainer/env"
openssl genrsa -out host.key 4096
kubectl -n containerssh create secret generic containerssh-hostkey --from-file=host.key
kubectl -n containerssh create secret generic agentainer-authorized-keys \
  --from-file=authorized_keys="$HOME/.ssh/id_ed25519.pub"
kubectl apply -k deploy/kubernetes
ssh dev@<containerssh service address>
```

- ContainerSSH asks for a host key from `openssl genrsa`, not `ssh-keygen` ([installation](https://containerssh.io/v0.6/reference/installation/)).
- The SSH username is `AGENTAINER_USER` in `deploy/kubernetes/auth-webhook/deployment.yaml` (`dev` by default).
- The webhook accepts plain `authorized_keys` lines only. It refuses a line with options such as `from=` or `command=`, because it cannot enforce them (`tests/unit/test_webhook.py`). Password logins always fail.
- Edit `loadBalancerSourceRanges` in `deploy/kubernetes/containerssh/service.yaml` to your client range before you apply.
- Pin the image in `deploy/kubernetes/agentainer/kustomization.yaml` (`images`, `newTag`). The example follows `latest`.
- `deploy/kubernetes/agentainer/networkpolicy.yaml` allows only DNS and outbound HTTPS. It is off by default; add it to that folder's `kustomization.yaml` to use it.
- A cluster has no host folder. Clone repos into `/workspace`. **Work you have not pushed exists only on the workspace volume.**
- sftp and scp are not supported: the image has no `sftp-server`.
- To turn sudo on, follow the comment in `deploy/kubernetes/agentainer/statefulset.yaml`. The capability list there is not verified yet, and the pod then needs the Baseline profile.

Multi-user is a documented path, not built: the webhook's `/config` answer would name a per-user pod such as `agentainer-<user>-0`, each user would get a StatefulSet and volumes, and `authorized_keys` would become a per-user mapping. The image stays the same.

The ContainerSSH-to-webhook traffic is plain HTTP inside the cluster. ContainerSSH's webhook client accepts `cacert`, `cert` and `key` settings for TLS (`config/http.go` in ContainerSSH v0.6.0).

## OpenRouter

| Command | What it does |
|---|---|
| `openrouter-claude` | Runs `claude` against `https://openrouter.ai/api` with `OPENROUTER_API_KEY`, for that process only ([OpenRouter guide](https://openrouter.ai/docs/cookbook/coding-agents/claude-code-integration)) |
| `openrouter-codex` | Runs `codex` with an `openrouter` provider and the model `~openai/gpt-sol-latest`. `-m` picks another model ([OpenRouter guide](https://openrouter.ai/docs/cookbook/coding-agents/codex-cli)). |
| `opencode` | Built-in provider. Set `OPENROUTER_API_KEY` and use models such as `openrouter/<vendor>/<model>`. |

`tests/90-openrouter.sh` checks, against a local fake endpoint, that the key arrives as a bearer token and appears in no argument list, log or file. Antigravity has no OpenRouter support.

Limits: Anthropic "doesn't support routing Claude Code to non-Claude models through any gateway" ([LLM gateway](https://code.claude.com/docs/en/llm-gateway)). Codex accepts only `wire_api = "responses"`, so the endpoint must serve the OpenAI Responses API ([Codex config reference](https://learn.chatgpt.com/docs/config-file/config-reference)).

## Security

The container isolates host files outside the mounts, host credentials you do not pass in, and other host processes.

It does not isolate:

- The code you mount. Agents can change or delete it.
- Outbound network access, unless you use the NetworkPolicy in Kubernetes.
- Credentials. **Every variable in the env file or Secret is readable by every process in the container**: all four agents, the tools they run, and MCP servers. Pass only the keys you need and prefer narrowly scoped tokens.
- The host kernel. This is a container, not a VM.
- Everything inside the container once sudo is on.

Agents keep their own approval prompts. The image turns on no skip-permissions mode. If you turn one on, note Anthropic's warning: "When executed with `--dangerously-skip-permissions`, dev containers do not prevent a malicious project from exfiltrating anything accessible inside the container, including the Claude Code credentials" ([devcontainer docs](https://code.claude.com/docs/en/devcontainer)).

Antigravity's terms say: "Wrapping `agy` inside third-party coding agents or applications ... is not supported under consumer plans" ([Antigravity FAQ](https://antigravity.google/docs/faq.md)). Agentainer installs `agy` for you to run yourself and does not wrap it.

Gemini CLI is not included. Google wrote: "On June 18, 2026, Gemini CLI and Gemini Code Assist IDE extensions will stop serving requests for Google AI Pro and Ultra, as well as those using it free of charge using Gemini Code Assist for individuals" ([Google Developers Blog](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/)). Antigravity CLI is Google's named replacement.

Other controls: the image runs as the non-root user `agent` (UID 1000), agent binaries are root-owned, and CI fails the build if trivy finds a secret in the image.

## Versions and updates

- `versions.env` pins every input: the base image digest, the apt snapshot date, each agent and tool version, and the checksum of every download. The build checks each download against it.
- Agents do not update themselves: `DISABLE_UPDATES=1` for Claude Code ([env vars](https://code.claude.com/docs/en/env-vars)), `/etc/codex/requirements.toml` for Codex ([managed configuration](https://learn.chatgpt.com/docs/enterprise/managed-configuration)), `AGY_CLI_DISABLE_AUTO_UPDATE=true` for Antigravity ([troubleshooting](https://antigravity.google/docs/cli/troubleshooting.md)), and `"update": "disable"` for OpenCode (`tests/40-agents.sh`, `tests/60-agents-md.sh`).
- A weekly workflow (`.github/workflows/bump.yml`) resolves new versions with `scripts/bump_versions.py` and opens a pull request against `develop`. A maintainer reviews and merges it by hand.
- Releases are calendar versions (`YYYY.MM.DD`). Images are tagged `latest`, the version and `sha-<commit>`, signed with cosign keyless, and published with an SBOM and provenance to `ghcr.io/chadmayfield/agentainer`. A published image is a fresh build from the release commit with the same pinned inputs, not the exact image the pull request tests ran on.
- `/etc/agentainer/versions.json` in the image lists every agent, tool and installed apt package version.

## Building and testing

```sh
scripts/build.sh                 # Podman by default; RUNTIME=docker for Docker
sh tests/run.sh                  # container tests against localhost/agentainer:dev
sh tests/lint.sh                 # shellcheck and shfmt, run from the image
python3 -m unittest discover -s tests/unit
```

## License

MIT, see `LICENSE`.
