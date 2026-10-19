# Contributing

This file covers how to work on Agentainer. The rules every change follows, for people and AI coding agents alike, are in [AGENTS.md](AGENTS.md).

## Branches

The repo uses git-flow:

- `develop` is the default branch. Open pull requests against it.
- Work on a `feature/<name>` branch made from `develop` (`git flow feature start <name>`, or `git switch -c feature/<name> develop`).
- `main` holds releases and changes only through release pull requests.
- Merged branches are deleted automatically. Merge with "Create a merge commit"; squash and rebase merges are turned off.

## Build and test

You need Podman or Docker.

```sh
scripts/build.sh                            # builds localhost/agentainer:dev for your architecture
sh tests/run.sh                             # container tests against that image
sh tests/lint.sh                            # shellcheck and shfmt, run from the image
python3 -m unittest discover -s tests/unit  # unit tests, no container needed
sh tests/host/test-launcher.sh              # launcher tests, no container needed
sh tests/host/test-manifests.sh             # Kubernetes manifest tests (kubectl, and the image for yq)
```

With Docker, prefix the commands with `RUNTIME=docker`. `IMAGE=<name>` tests another image.

## CI

[`.github/workflows/build.yml`](.github/workflows/build.yml) runs on every pull request and every push to `develop` and `main`:

- lint and unit tests, actionlint;
- an image build on amd64 and arm64, the container tests under Docker and rootless Podman, a check that the agents start on a CPU without AVX2, and trivy scans (a secret fails the build; vulnerabilities are reported).

A pull request that changes only `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE` or files under `docs/` skips the image job. The required check is `ci`, which passes only when every job passed or the image job was skipped for a docs-only change.

## Releases

1. From an up-to-date `develop`, run `git flow release start <version>`. The version is the release date, `YYYY.MM.DD`, with `.N` for a second release that day.
2. Push the branch and open a pull request from `release/<version>` to `main`.
3. When `ci` passes, merge it with "Create a merge commit". The `version` job reads the version from the merge commit's subject (`Merge pull request #N from <owner>/release/<version>`).
4. The workflow on `main` builds both architectures, pushes them, tags the index `latest`, `<version>` and `sha-<short>`, signs it and each architecture's image with cosign, and creates the tag `v<version>` and a GitHub release with the vulnerability summary.
5. Open a pull request from `main` to `develop` to bring back any fixes made on the release branch.

Do not run `git flow release finish`: it merges into `main` locally. A hotfix is a new release made the same way; a `hotfix/*` branch merged into `main` does not publish.

Re-running a failed release is safe: the `version` job checks only for the git tag, which is created last.

## The bump GitHub App

The weekly update ([`.github/workflows/bump.yml`](.github/workflows/bump.yml)) opens its pull request with a GitHub App token, so CI starts without "Approve workflows to run". To set the App up:

1. Under your account's Settings, Developer settings, GitHub Apps, create a new App. Use the repository URL as its homepage and turn off its webhook.
2. Give it the repository permissions Contents (read and write) and Pull requests (read and write), and nothing else. Allow installing it only on your account.
3. Copy its Client ID (not the App ID) and generate a private key.
4. Install the App on the `agentainer` repository only.
5. In the repository's Settings, Secrets and variables, Actions, add the variable `BUMP_APP_CLIENT_ID` (the Client ID) and the secret `BUMP_APP_PRIVATE_KEY` (the whole `.pem` file). Then delete the downloaded key file.
6. Run `gh workflow run bump.yml`. If it opens a pull request, its CI starts on its own, and the commit author is the App's bot user.

Without the variable and secret, the workflow uses `GITHUB_TOKEN`. If the variable is set but the key is wrong, the job fails instead of falling back; remove the variable to go back to `GITHUB_TOKEN`.

## Security problems

Do not open a public issue. See [SECURITY.md](SECURITY.md).
