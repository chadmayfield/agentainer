# Security policy

## Reporting a vulnerability

Report vulnerabilities privately through GitHub: open the repository's **Security** tab and choose **Report a vulnerability**. Do not open a public issue for a security problem.

Include what you found, how to reproduce it, and the image tag or digest you used (`docker image inspect <image> --format '{{index .Config.Labels "org.opencontainers.image.version"}}'`).

## What is in scope

- The image build: `Containerfile`, `build/`, and the pins in `versions.env`.
- The scripts the image ships in `rootfs/`, such as the entrypoint and `agentainer-mcp`.
- The launcher `bin/agentainer`.
- The Kubernetes example in `deploy/kubernetes/`, including the auth webhook.
- The CI workflows in `.github/workflows/`.

A vulnerability in an agent or tool that the image installs (Claude Code, Codex, Antigravity CLI, OpenCode, Go, gh and the others) belongs to that project. Report it there. Once the project ships a fix, a scheduled or manually triggered version bump brings it into the image.

## Supported versions

Only the latest release receives fixes. Releases are calendar versions (`YYYY.MM.DD`), and the image tag `latest` follows the newest one.

## Known limits

[docs/security.md](docs/security.md) lists what the container does and does not isolate. The main points: every credential passed to the container is readable by every process in it, the agents can change the code you mount, and the ContainerSSH webhook uses plain HTTP inside the cluster unless you turn on TLS.

Each release lists its trivy findings in the release notes and attaches the full reports ([docs/security.md](docs/security.md#vulnerability-reports)).
