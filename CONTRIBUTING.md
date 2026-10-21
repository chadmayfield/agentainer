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

[`.github/workflows/build.yml`](.github/workflows/build.yml) runs on every pull request, every push to `develop` and `main`, and every `v*` tag push. A pull request also runs it again when you edit it, which includes changing its base branch:

- the `lint-unit` job: actionlint, the Python unit tests, and the launcher, `scripts/build.sh` and `build/fetch.sh` tests;
- the `image` job, on amd64 and arm64: the image build, shellcheck and shfmt (`tests/lint.sh` runs them from the image), the container tests and real launcher lifecycle under Docker and rootless Podman, a custom UID/GID build, the manifest tests, a check that the agents start on a CPU without AVX2, and trivy scans (a secret fails the build; vulnerabilities are reported).

The `layer-repro` job runs on amd64 and arm64 and uses the pinned BuildKit image to build an isolated copy of every tool twice with no cache. It compares the exported tool-layer digests. This checks unchanged inputs; it does not test every possible combination of pin changes. The required `ci` check includes this job.

The image and layer comparison jobs are skipped when every changed file is `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE` or a file under `docs/` other than `docs/kubernetes.md` (the manifest tests check its install commands). For a pull request, the changed files are what the merge adds to the base branch. For a push to `develop`, they are the files changed since the previous tip. A push to `main` and a pull request whose base branch changed always build the image. A docs-only change gets no shell lint, because no shell file changed. The required check is `ci`, which passes only when every job passed or the image job was skipped for a docs-only change.

## Signing local commits

Configure signing once in your checkout, with your own full GPG fingerprint and a key whose UID uses your GitHub noreply address:

```sh
git config --local user.signingkey YOUR_FULL_GPG_FINGERPRINT
git config --local gpg.format openpgp
git config --local commit.gpgsign true
git config --local tag.gpgsign true
```

These settings stay in `.git/config`, apply to this local clone and its worktrees, and are not shared with contributors or other clones. Register the public key on your GitHub account so GitHub can verify signatures. Keep the private key on your signing host. A signing failure stops the commit; fix access to the key instead of disabling signing. Verify a new commit with `git verify-commit HEAD` ([Git configuration](https://git-scm.com/docs/git-config), [commit verification](https://git-scm.com/docs/git-verify-commit)). GitHub-generated merge commits and automated bump commits use their own identities.

## Releases

1. From an up-to-date `develop` whose CI passed, run `git flow release start <version>`. Use SemVer, such as `0.1.0`, or a dated development prerelease, such as `0.1.0-dev.20261019.1` ([version policy](docs/versions.md#releases)).
2. Push the branch and open a pull request from `release/<version>` to `main`.
3. When `ci` passes, merge with "Create a merge commit". The subject must be exactly `Merge pull request #N from <owner>/release/<version>`. A push to `main` tests the merge but does not publish.
4. Fetch the merged commit, create a signed annotated tag `v<version>` on that exact merge commit with `git tag -s v<version> <merge-commit> -m "Release v<version>"`, verify it with `git verify-tag v<version>`, then push only that tag with `git push origin refs/tags/v<version>` ([signed tags](https://git-scm.com/docs/git-tag)). Do not tag the release branch's pre-merge tip.
5. The tag push runs CI. After aggregate CI passes, `scripts/check_release_tag.py` requires a two-parent release merge on main's first-parent history, a matching tag version and target, and a valid GPG signature by the trusted primary key. It retrieves the owner's public key from GitHub and verifies in a temporary keyring. Set the repository Actions variable `RELEASE_SIGNING_FINGERPRINT` to that full uppercase fingerprint. The signing key must be registered on the repository owner's GitHub account, or on the account named by the optional `RELEASE_SIGNER` Actions variable for an organization-owned repository ([public GPG keys API](https://docs.github.com/en/rest/users/gpg-keys)). A missing key setting, unsigned tag or existing GitHub release stops publishing.
6. The publish jobs build and push both architectures. The release job assembles an index with only `sha-<short>`, signs it and the platform manifests with cosign, then creates a GitHub provenance attestation for the index. The attestation is stored in GitHub and GHCR. Verification must pass before version or `latest` tags move: exact workflow identity, source commit and tag ref for GitHub provenance; expected repository and commit in each platform's BuildKit provenance; signatures, SBOM descriptors and native startup. The highest stable version alone can move `latest`. Prereleases remain explicitly excluded from latest. The GitHub release uses `--verify-tag`, preserving the maintainer-signed tag.
7. Open a pull request from `main` to `develop` to bring back fixes made on the release branch.

Do not run `git flow release finish`: it merges into `main` locally. A hotfix is a new release made the same way. A `hotfix/*` merge does not authorize publication.

Re-run a failed tag workflow without replacing the signed tag. A failure before verification and the retag dry run pass leaves the version and `latest` tags unchanged. A rebuilt image gets a new digest; it must be signed, attested and verified again before promotion. Once the GitHub release exists, its version cannot be republished. Use a new version for further changes.

CI holds no maintainer private signing key. It verifies the GPG-signed release tag using the maintainer's public key, then uses GitHub OIDC for container image signatures and attestations.

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
