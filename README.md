# Agentainer

Agentainer is one container image with four AI coding agents and a shared set of developer tools. You run it in a terminal on a laptop, a server or a Kubernetes cluster.

- Agents: [Claude Code](https://code.claude.com/docs/en/setup), [Codex CLI](https://github.com/openai/codex), [Antigravity CLI](https://antigravity.google/docs/cli/overview.md) (`agy`) and [OpenCode v2](https://opencode.ai/v2/docs).
- Base: Ubuntu 26.04 LTS, pinned by digest, with apt packages from the [Ubuntu snapshot service](https://documentation.ubuntu.com/server/how-to/software/snapshot-service/) at a pinned date.
- Tools: git, gh, Go, Rust, Python with uv and pipx, Node.js, ripgrep, jq, yq, shellcheck, trivy and more. `/etc/agentainer/versions.json` in the image lists every version.
- Platforms: `linux/amd64` and `linux/arm64`. On amd64 the agents also run on CPUs without AVX2; CI checks this on every build.

Agents see only what you mount and the credentials you pass in, and the same image and tools run everywhere.

## Quick start

You need Podman or Docker. The launcher [`bin/agentainer`](bin/agentainer) is a POSIX shell script.

No image is published to `ghcr.io/chadmayfield/agentainer` until the first release. Until then, build it with `scripts/build.sh` and set `AGENTAINER_IMAGE=localhost/agentainer:dev`.

```sh
mkdir -p ~/.config/agentainer
cp env.example ~/.config/agentainer/env
chmod 600 ~/.config/agentainer/env      # then fill in the keys you use
bin/agentainer up ~/code                 # ~/code becomes /workspace
bin/agentainer attach                    # tmux session "main"
```

Start an agent in a tmux window (`claude`, `codex`, `agy` or `opencode`). Close the terminal whenever you like. `bin/agentainer attach` brings you back to the same session with the agents still running.

## Documentation

| Topic | Read |
|---|---|
| Launcher commands, `docker run` and `podman run`, sudo, file ownership, upgrading | [docs/running.md](docs/running.md) |
| Signing in to each agent, which Claude login wins, GitHub tokens | [docs/logins.md](docs/logins.md) |
| The shared `AGENTS.md`, MCP servers, tools that agents install, OpenRouter | [docs/configuration.md](docs/configuration.md) |
| Kubernetes with ContainerSSH | [docs/kubernetes.md](docs/kubernetes.md) |
| What the container isolates, and vulnerability reports | [docs/security.md](docs/security.md) |
| Pinned versions, weekly updates, releases and signatures | [docs/versions.md](docs/versions.md) |
| Error messages and their fixes | [docs/troubleshooting.md](docs/troubleshooting.md) |

To report a vulnerability, follow [SECURITY.md](SECURITY.md). To contribute, read [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT, see [LICENSE](LICENSE). The image also contains software under other licenses.
