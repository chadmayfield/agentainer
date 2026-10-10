# Contributing

Thanks for helping. This file is for people. `AGENTS.md` holds the same rules in more detail for AI coding agents, and both apply.

## Branches

The repo uses git-flow:

- `develop` is the default branch. Open pull requests against it.
- Work on a `feature/<name>` branch made from `develop` (`git flow feature start <name>`, or `git switch -c feature/<name> develop`).
- `main` holds releases and changes only through release pull requests. Do not open pull requests against `main`.

## Build and test

You need Podman or Docker. The maintainer uses Podman; CI runs both.

```sh
scripts/build.sh                            # builds localhost/agentainer:dev for your architecture
sh tests/run.sh                             # container tests
sh tests/lint.sh                            # shellcheck and shfmt, run from the image
python3 -m unittest discover -s tests/unit  # unit tests, no container needed
sh tests/host/test-launcher.sh              # launcher tests, no container needed
```

With Docker, prefix the commands with `RUNTIME=docker`. CI runs all of these on amd64 and arm64, under Docker and rootless Podman, and adds a trivy secret scan that fails the build on any finding.

## Rules for changes

- Pin every new download in `versions.env` with its checksum, and teach `scripts/bump_versions.py` to resolve it. Never hardcode a version in the `Containerfile` or a script.
- Cite the official source for any version, flag, path or behavior you rely on, in a comment or the pull request.
- Never commit credentials, or hostnames, IP addresses or domains from real infrastructure. Use `example.com` and `203.0.113.0/24` in examples.
- Image files stay outside `/home/agent`. The entrypoint may only add missing files to a home volume, never overwrite one.
- Add or change a test with each behavior change. A bug fix starts with a test that fails.
- Shell scripts must pass `shellcheck` and `shfmt`.

## Vulnerabilities in bundled tools

- Install upstream release binaries and check them against the checksum the project publishes. Do not build a tool from source to pick up a newer Go, Rust or library version.
- Findings that sit inside an upstream binary are reported, not chased. CI lists them, with the number that have a fix, and a new upstream release reaches the image through the weekly version bump.
- When a tool stops shipping releases and carries a critical finding that only a rebuild would fix, the maintainer decides whether to keep it, drop it or replace it. Record the decision in the pull request that makes it.

## Writing

Docs, comments, commit messages and pull request text use plain, direct sentences in active voice, sentence-case headings, and no em dashes. Say what something does, with the command, path or number.

## Security problems

Do not open a public issue. See `SECURITY.md`.
