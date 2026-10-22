# Security

To report a vulnerability in Agentainer itself, follow [SECURITY.md](../SECURITY.md).

## Contents

- [What the container isolates](#what-the-container-isolates)
- [Agent permissions](#agent-permissions)
- [Vulnerability reports](#vulnerability-reports)

## What the container isolates

The container restricts direct filesystem and process access through its mounts and namespaces. Writable mounts, shared home files and reachable host services can let container code affect the host.

It does not isolate:

- The code you mount. Agents can change or delete it.
- Host execution of mounted files. Git configuration and hooks, generated executables, editor tasks and project scripts can run as your host user after an agent changes them. Review these files before running host commands, or use a separate host clone. Disabling Git hooks alone does not disable every execution path ([Git configuration](https://git-scm.com/docs/git-config)).
- Host network services. On the tested macOS Podman machine, `host.containers.internal` reached a temporary service bound to host loopback. This does not establish the behavior of every runtime. Authenticate sensitive host services; use an offline network when network access is unnecessary ([Podman networking](https://docs.podman.io/en/latest/markdown/podman-run.1.html)).
- Shared home volumes. Every container using the same home trusts its shell startup files, agent settings and installed tools. Use different homes for different trust levels. Enabling sudo in a later container also grants its startup code access to container root.
- Forwarded SSH agents. Processes with access to the socket can request signatures with its loaded keys. Use a dedicated agent with only the required keys. Keys with confirmation constraints can require host approval ([ssh-add](https://man.openbsd.org/ssh-add)).
- Terminal output. Shells and attached panes send output to your host terminal. Arbitrary tmux passthrough is disabled by default. Enabling `allow-passthrough` in your own tmux configuration permits wrapped escape sequences to reach the outer terminal, including clipboard requests on terminals that accept them ([tmux manual](https://man.openbsd.org/tmux)).
- Outbound network access, unless you use the NetworkPolicy in Kubernetes ([docs/kubernetes.md](kubernetes.md#network-policy)).
- Credentials. **Every variable in the env file or Secret is readable by every process in the container**: all four agents, the tools they run, and MCP servers. Pass only the keys you need, and prefer narrowly scoped tokens.
- The host kernel. This is a container, not a VM.
- Everything inside the container once sudo is on ([docs/running.md](running.md#sudo)).

The image runs as the non-root user `agent` (UID 1000), agent binaries are root-owned, and agents cannot update themselves while sudo is off.

## Agent permissions

Agents keep their own approval prompts; the image turns on no skip-permissions mode. If you turn one on, note Anthropic's warning: "When executed with `--dangerously-skip-permissions`, dev containers do not prevent a malicious project from exfiltrating anything accessible inside the container, including the Claude Code credentials" ([devcontainer docs](https://code.claude.com/docs/en/devcontainer)).

Codex's own sandbox is off (`sandbox_mode = "danger-full-access"` in the seeded `~/.codex/config.toml`). Its bubblewrap sandbox failed in the tested container with "bwrap: Can't mount devpts on /newroot/dev/pts: Permission denied", so the container provides the isolation. The seeded `approval_policy = "on-request"` permits approval requests; it does not require confirmation for every command. Codex can run commands against mounted files and use available network access without prompting. Treat every writable mount and supplied credential as accessible to it ([OpenAI approval semantics](https://learn.chatgpt.com/docs/agent-approvals-security)).

Antigravity's terms say: "Wrapping `agy` inside third-party coding agents or applications ... is not supported under consumer plans" ([Antigravity FAQ](https://antigravity.google/docs/faq.md)). Agentainer installs `agy` for you to run yourself and does not wrap it.

Gemini CLI is not included. Google wrote: "On June 18, 2026, Gemini CLI and Gemini Code Assist IDE extensions will stop serving requests for Google AI Pro and Ultra, as well as those using it free of charge using Gemini Code Assist for individuals" ([Google Developers Blog](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/)). Antigravity CLI is Google's named replacement.

## Vulnerability reports

CI scans every image with trivy. A secret found in the image fails the build. Vulnerabilities are reported and do not fail it.

- Pull requests and `develop`: the run's summary page shows counts by severity, how many have a fix, and up to 50 critical findings. The full trivy JSON is the `vulnerabilities-<arch>` artifact on that run.
- Releases: the scan runs on the images pushed to GHCR. The release notes start with the same summary, and `vulnerabilities-amd64.json` and `vulnerabilities-arm64.json` are attached to the release.
- Kernel CVEs filed against `linux-libc-dev`, the kernel header package that C compilers need, are counted separately: the container runs on the host's kernel.

Many findings sit in upstream binaries that this repo installs as released. They are fixed by upstream releases, which reach the image through the scheduled version update ([docs/versions.md](versions.md)). [AGENTS.md](../AGENTS.md#vulnerabilities-in-bundled-tools) describes how a tool that stops shipping fixes is handled.
