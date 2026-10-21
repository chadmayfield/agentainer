# Security

To report a vulnerability in Agentainer itself, follow [SECURITY.md](../SECURITY.md).

## What the container isolates

The container keeps agents away from host files outside the mounts, host credentials you do not pass in, and other host processes.

It does not isolate:

- The code you mount. Agents can change or delete it.
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
