# AGENTS.md

Instructions for AI coding agents working on this repository. Claude Code, Codex, Antigravity CLI and OpenCode all read this file. Do not add a `CLAUDE.md`: Claude Code reads `AGENTS.md` only when no `CLAUDE.md` exists in the working directory or above it.

## What this repo is

Agentainer is one public container image that bundles several AI coding agents (Claude Code, Codex CLI, Antigravity CLI, OpenCode) and a shared toolset. It runs locally with Docker or Podman and in Kubernetes through ContainerSSH. If `docs/spec.md` (design) and `docs/plan.md` (build steps) exist in your checkout, read both before changing anything. They may be kept out of git, so never `git add` them unless the maintainer asks.

## Verify, never guess

- Every package name, version, install command, config path, file name, flag and URL must come from the tool's official docs, its official repository, or a command you ran. Cite the source next to the fact in docs and in commit or PR text.
- If you cannot verify something, write "not verified" and ask the maintainer. If sources disagree, show both and let the maintainer choose.
- Check a CLI flag with `--help`, a man page or the tool's source before you use it.
- A recommendation is not a decision. Design changes need the maintainer's approval first.

## Public and generic

- The repo is public and MIT licensed. Anyone must be able to use it.
- Never commit internal information: hostnames, IP addresses, cluster names, registry names, domains or network details from anyone's own infrastructure. Use placeholders such as `example.com` in examples.
- Never put credentials in the image, in any layer, or in the repo. Credentials come in at run time through environment variables or the persistent home volume.

## Git workflow (git-flow)

- `main` holds releases. `develop` is the integration branch and the GitHub default branch.
- Do all work on a `feature/<name>` branch created from `develop` (`git flow feature start <name>`). Open pull requests against `develop`.
- Never push to `main` directly, and do not use `git flow release finish`, because it merges into `main` locally. A release is `git flow release start <version>`, then a pull request from `release/<version>` to `main`, then a pull request from `main` back to `develop`.
- Before each commit, show a file-by-file summary of what changed and wait for the maintainer's approval.
- End every commit message with this trailer:

  ```
  Co-Authored-By: Claude <noreply@anthropic.com>
  ```

- Do not force-push, rewrite published history, or delete branches without explicit instruction.

## Working on the host

- Do not install software on the maintainer's machine without asking first.
- Building and running containers locally is allowed once the maintainer has approved the implementation plan.
- Do not deploy to any Kubernetes cluster without explicit approval for that deployment.

## Repo conventions

- The build file is `Containerfile`. Docker needs `-f Containerfile`; Podman finds it by default.
- Every pinned version, digest and checksum lives in `versions.env`. Do not hardcode versions in the `Containerfile` or scripts.
- Upstream downloads are checked against the checksum the project publishes. When a project publishes none, record the SHA-256 you computed in `versions.env` and say so in a comment.
- Image-owned files live outside `/home/agent`. The entrypoint may only add missing files to the home volume. It must never overwrite a file the user owns.
- Shell scripts must pass `shellcheck` and be formatted with `shfmt`.
- Run the tests in `tests/` before asking for a commit, and report the real results, including failures.

## Writing style

These rules apply to docs, the README, commit messages, PR text, code comments and user-facing messages.

- Plain, direct sentences. Sentence-case headings.
- No em dashes. Use periods or commas.
- No filler ("in order to", "it is important to note"), no hype words ("seamless", "robust", "powerful"), no emojis.
- Say what a thing does, with the command, path or number, not how it feels.
- Prefer active voice.
