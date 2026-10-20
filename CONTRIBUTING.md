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
sh tests/host/test-build-script.sh          # scripts/build.sh tests, no container needed
sh tests/host/test-fetch.sh                 # fetch.sh and Rust manifest check tests, no container needed
sh tests/host/test-manifests.sh             # Kubernetes manifest tests (kubectl, and the image for yq)
sh tests/host/test-launcher-integration.sh  # real engine, existing local image
sh tests/host/test-build-uid.sh             # slow: builds a full image with --uid 1001 --gid 20
python3 tests/host/test-layer-repro.py      # slow: two clean tool builds, configured Buildx
```

With Docker, prefix the commands with `RUNTIME=docker`. `IMAGE=<name>` tests another image.

## CI

[`.github/workflows/build.yml`](.github/workflows/build.yml) runs on every pull request and every push to `develop` and `main`. A pull request also runs it again when you edit it, which includes changing its base branch:

- the `lint-unit` job: actionlint, the Python unit tests, and the launcher, `scripts/build.sh` and `build/fetch.sh` tests;
- the `image` job, on amd64 and arm64: the image build, shellcheck and shfmt (`tests/lint.sh` runs them from the image), the container tests and real launcher lifecycle under Docker and rootless Podman, a custom UID/GID build, the manifest tests, a check that the agents start on a CPU without AVX2, and trivy scans (a secret fails the build; vulnerabilities are reported).

The `layer-repro` job runs on amd64 and arm64 and uses the pinned BuildKit image to build an isolated copy of every tool twice with no cache. It compares the exported tool-layer digests. This checks unchanged inputs; it does not test every possible combination of pin changes. The required `ci` check includes this job.

The image and layer comparison jobs are skipped when every changed file is `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE` or a file under `docs/` other than `docs/kubernetes.md` (the manifest tests check its install commands). For a pull request, the changed files are what the merge adds to the base branch. For a push to `develop`, they are the files changed since the previous tip. A push to `main` and a pull request whose base branch changed always build the image. A docs-only change gets no shell lint, because no shell file changed. The required check is `ci`, which passes only when every job passed or the image job was skipped for a docs-only change.

## Releases

1. From an up-to-date `develop`, run `git flow release start <version>`. The version is the release date, `YYYY.MM.DD`, with `.N` for a second release that day.
2. Push the branch and open a pull request from `release/<version>` to `main`.
3. When `ci` passes, merge it with "Create a merge commit". The `version` job reads the version from the merge commit's subject, which must be exactly `Merge pull request #N from <owner>/release/<version>`, where `<owner>` is the repository owner and `<version>` is a real date. Any other push to `main` fails the `version` job and publishes nothing.
4. The workflow on `main` builds both architectures and pushes them. The `release` job then tags the multi-architecture index only `sha-<short>`, checks its annotations, and signs it and each architecture's image with cosign. Only after that does it point `<version>` at the signed digest. While holding the release lock, it refreshes `main` and compares calendar versions from its first-parent release merges. Historical release names that are not valid calendar versions are ignored; the candidate version must still be valid and present in history. Only the highest merged version can move `latest`; an older build or retry keeps its own version tag without rolling `latest` back. A failed history refresh stops publication. After publishing the image tags, a read-only test verifies the index and both platform signatures against the build workflow identity, checks their SBOM and provenance attestation descriptors, and pulls and starts the native platform by the verified index digest. Its last step creates the tag `v<version>` and a GitHub release with the vulnerability summary.
5. Open a pull request from `main` to `develop` to bring back any fixes made on the release branch.

Do not run `git flow release finish`: it merges into `main` locally. A hotfix is a new release made the same way; a `hotfix/*` branch merged into `main` does not publish.

Re-running a failed release is safe. The `version` job checks only for the git tag, which is created last. A failure before signing leaves `latest` and `<version>` on the last signed release. A `publish` job that runs again replaces its `digest-<arch>` artifact, and the `release` job stops unless it finds exactly one digest for each architecture. A rebuilt image gets a new digest, so the new index does too. The version tag moves to it after signing; `latest` moves only when that version is still the highest release merged into `main`.

## The bump GitHub App

The scheduled update ([`.github/workflows/bump.yml`](.github/workflows/bump.yml)) opens its pull request with a GitHub App token, so CI starts without "Approve workflows to run". To set the App up:

1. Under your account's Settings, Developer settings, GitHub Apps, create a new App. Use the repository URL as its homepage and turn off its webhook.
2. Give it the repository permissions Contents (read and write) and Pull requests (read and write), and nothing else. Allow installing it only on your account.
3. Copy its Client ID (not the App ID) and generate a private key.
4. Install the App on the `agentainer` repository only.
5. In the repository's Settings, Secrets and variables, Actions, add the variable `BUMP_APP_CLIENT_ID` (the Client ID) and the secret `BUMP_APP_PRIVATE_KEY` (the whole `.pem` file). Then delete the downloaded key file.
6. Run `gh workflow run bump.yml`. If it opens a pull request, its CI starts on its own, and the commit author is the App's bot user.

Without the variable and secret, the workflow uses `GITHUB_TOKEN`. If the variable is set but the key is wrong, the job fails instead of falling back; remove the variable to go back to `GITHUB_TOKEN`.

## Security problems

Do not open a public issue. See [SECURITY.md](SECURITY.md).
