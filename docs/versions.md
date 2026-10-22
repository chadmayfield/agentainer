# Versions, updates and releases

## Contents

- [Pinned inputs](#pinned-inputs)
- [Agents do not update themselves](#agents-do-not-update-themselves)
- [Scheduled updates](#scheduled-updates)
- [Releases](#releases)

## Pinned inputs

[`versions.env`](../versions.env) pins every input of the image: the base image digest, the apt snapshot date, each agent and tool version, and the checksum of every download. The build checks each download against it. The one exception is the Rust toolchain: `rustup-init` downloads the components and checks each against the hashes in Rust's own channel manifest.

Claude Code is the native binary from Anthropic's release host, the file Anthropic's native installer downloads. The scheduled update checks the release's `manifest.json` against Anthropic's GPG signature before it pins the binary's SHA-256 ([binary integrity](https://code.claude.com/docs/en/setup#binary-integrity-and-code-signing)).

Each tool is built in its own stage. In the layers the release build creates, any file time later than `SOURCE_DATE_EPOCH` from `versions.env` is set to it (BuildKit's `rewrite-timestamp` option). A layer whose tool did not change is then byte-identical to the previous release's, as long as the same BuildKit version (`BUILDKIT_IMAGE`) compressed it, so updating the image downloads only the layers that changed. A release that updates BuildKit can change every layer's digest. `scripts/build.sh` does the same with Podman 5.6 or later. An older Podman server ignores the options, so the script leaves them out and prints a warning; the image works the same, but every layer gets a new digest.

`/etc/agentainer/versions.json` in the image lists every pin and every installed apt package version.

## Agents do not update themselves

| Agent | Setting |
|---|---|
| Claude Code | `DISABLE_UPDATES=1` ([env vars](https://code.claude.com/docs/en/env-vars)) |
| Codex | `/etc/codex/requirements.toml` ([managed configuration](https://learn.chatgpt.com/docs/enterprise/managed-configuration)) |
| Antigravity | `AGY_CLI_DISABLE_AUTO_UPDATE=true` ([troubleshooting](https://antigravity.google/docs/cli/troubleshooting.md)) |
| OpenCode | `"update": "disable"` in its global config, `~/.config/opencode/opencode.json` ([config](https://opencode.ai/v2/docs/config); OpenCode ignores the setting in project config) |

New versions arrive only with a new image.

## Scheduled updates

On the 1st and 15th of each month at 06:00 UTC, [`.github/workflows/bump.yml`](../.github/workflows/bump.yml) resolves the newest upstream versions with [`scripts/bump_versions.py`](../scripts/bump_versions.py) and opens a pull request against `develop`. It refuses to write any value that does not match the expected format for its pin. The pull request's build page shows which pins changed. A maintainer reviews and merges it by hand, and nothing is published until the next release.

Run the same workflow manually through its `workflow_dispatch` trigger for an urgent security fix or an upstream change that breaks an agent. GitHub documents [scheduled](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule) and [manual](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch) triggers.

The workflow opens the pull request with a GitHub App token when the repository has the variable `BUMP_APP_CLIENT_ID` and the secret `BUMP_APP_PRIVATE_KEY`; CI then starts on its own. Without them it uses `GITHUB_TOKEN`, and GitHub holds the pull request's CI until a maintainer chooses "Approve workflows to run" ([CONTRIBUTING.md](../CONTRIBUTING.md#the-bump-github-app) describes the App).

## Releases

Releases use [Semantic Versioning](https://semver.org/). Stable versions have the form `MAJOR.MINOR.PATCH`, such as `0.1.0`. Development prereleases use the next intended version followed by `-dev.YYYYMMDD.N`, such as `0.1.0-dev.20261019.1`. The date must exist and the build number starts at 1. Increment it for another build that day. The parser also accepts other SemVer prerelease identifiers, such as `0.1.0-rc.1`. Container tags exclude SemVer build metadata (`+...`) and are limited to 128 characters ([distribution tag format](https://github.com/distribution/reference/blob/main/regexp.go)).

Versions below `1.0.0` are initial development, without a stable compatibility promise. Agentainer's public interfaces are its launcher commands, documented environment variables, configuration paths and persistent-home upgrade behavior. Bundled tool versions remain separate in `versions.env`.

A release requires a maintainer-signed annotated `v<version>` tag on the matching release merge in `main`. The tag signature must match the repository variable `RELEASE_SIGNING_FINGERPRINT`. The version job checks out `main` to run its authorization code, so a candidate tag cannot replace its signature gate. Protect `main` and release-tag creation in repository settings. A branch merge alone does not publish ([release procedure](../CONTRIBUTING.md#releases)). Each release publishes `ghcr.io/chadmayfield/agentainer` for amd64 and arm64:

- tagged with the version and `sha-<commit>`, with `latest` reserved for stable releases;
- signed with cosign keyless signing, the index and each architecture's image;
- with an SBOM and BuildKit provenance for each architecture, a signed GitHub provenance attestation for the multi-architecture index, and zstd-compressed layers.

A runtime needs zstd support to pull the image. These are the first versions with it:

| Runtime | First version that pulls zstd layers |
|---|---|
| Docker Engine | 23.0.0 ("Add support for pulling `zstd` compressed layers", [Engine 23.0 release notes](https://docs.docker.com/engine/release-notes/23.0/), moby/moby#41759) |
| containerd, including Kubernetes nodes that use it | 1.5.0 ("Add support for layers compressed with zstd", [containerd v1.5.0 release notes](https://github.com/containerd/containerd/releases/tag/v1.5.0)) |
| Podman | Not verified. Podman's release notes do not name a version. containers/image added zstd in containers/image#639, and Podman 1.6.2 is the first release whose `go.mod` uses a containers/image version with that change. |

The release job refreshes `main` while holding its release lock. Only the highest stable SemVer in main's first-parent release merges can move `latest`. Prereleases never move it, even when they target a higher version. A delayed older stable build or retry publishes its own version tag and leaves `latest` alone. Ordering is numeric, so `0.1.10` follows `0.1.2`, and `0.1.0-dev.20261019.10` follows `0.1.0-dev.20261019.2`. A version without a prerelease suffix follows every prerelease of that same version ([release script](../scripts/release-image.sh), [version comparison](../scripts/release_order.py)).

GitHub releases use the same latest decision. Versions with a prerelease suffix are marked as prereleases and explicitly excluded from latest ([GitHub CLI release flags](https://cli.github.com/manual/gh_release_create)). Before the first stable release, pull an explicit prerelease tag; `latest` does not exist yet.

```sh
podman pull ghcr.io/chadmayfield/agentainer:0.1.0-dev.20261019.1
AGENTAINER_IMAGE=ghcr.io/chadmayfield/agentainer:0.1.0-dev.20261019.1 bin/agentainer up
```

These commands require that version to have completed its release workflow. A merge to `develop` runs CI and does not publish an image.

The published image is a fresh build from the release commit with the same pinned inputs, not the exact image the pull request's tests ran on.

Each publish job checks the freshly pushed digest on its native architecture before uploading the digest artifact. It checks architecture and release labels, entrypoint completion, non-root execution and startup of all four agents ([platform check](../scripts/check-release-platform.sh)). A failure prevents index publication and promotion. Live execution of this additional gate in GitHub Actions is not verified until the next release.

Release publishing waits for aggregate CI and signed-tag verification. The release workflow signs the multi-architecture index and platform manifests, then uses [`actions/attest`](https://github.com/actions/attest) to attest the index digest. The attestation is stored in GitHub and pushed to GHCR. It links the index to the source commit and release tag without a long-lived signing key in CI.

Before moving version or `latest` tags, [`tests/host/test-published-image.py`](../tests/host/test-published-image.py) verifies:

- Index and platform signatures against the exact workflow identity for the release tag and GitHub OIDC issuer ([Sigstore CI verification](https://docs.sigstore.dev/quickstart/quickstart-ci/)).
- GitHub provenance against the repository, source commit, tag ref and workflow identity, rejecting self-hosted runners ([GitHub verification flags](https://cli.github.com/manual/gh_attestation_verify)).
- Both platforms' BuildKit provenance payloads against the expected source repository and commit. A dirty or different revision fails ([BuildKit provenance fields](https://docs.docker.com/build/metadata/attestations/slsa-provenance/)).
- SBOM and provenance descriptors bound to each platform manifest, followed by a pull and native startup by the verified index digest ([attestation storage](https://docs.docker.com/build/metadata/attestations/attestation-storage/)).

These checks enforce the named fields; they do not establish a SLSA level or validate every SBOM package entry. Fixtures exercise rejection cases in pull requests. The [release workflow for `v0.1.0-dev.20261019.1`](https://github.com/chadmayfield/agentainer/actions/runs/39373669375) completed signing, attestation storage and registry verification. Each later release must pass the same checks for its own digest.

The resolver follows current upstream release pointers without a minimum release age. Proposed binaries execute in build and test jobs before a bump pull request is reviewed. Checksums establish byte identity, not that an upstream release is safe. Review upstream changes before merging; a minimum release age and additional publisher-verification requirements are policy decisions.

## Verifying a release before use

Use a trusted checkout of this repository and independently installed Docker Buildx, cosign and GitHub CLI. Verify the maintainer-signed release tag with the trusted public key and fingerprint first. Obtain the full source commit from that tag and the image index digest from the registry. Review the digest before running the verifier; never substitute an unverified mutable tag afterward.

```sh
set -eu
version=0.1.0-dev.20261019.1
git verify-tag "v$version"
commit=$(git rev-parse "v$version^{commit}")
# Replace this placeholder with the release's full index digest.
digest=sha256:REPLACE_WITH_64_HEX_DIGITS
python3 tests/host/test-published-image.py ghcr.io/chadmayfield/agentainer "$digest" \
  "https://github.com/chadmayfield/agentainer/.github/workflows/build.yml@refs/tags/v$version" \
  https://token.actions.githubusercontent.com chadmayfield/agentainer "$commit" "refs/tags/v$version"
AGENTAINER_IMAGE="ghcr.io/chadmayfield/agentainer@$digest" bin/agentainer up
```

The verifier checks cosign identities, GitHub and BuildKit provenance, both platform signatures, and SBOM descriptors. It then pulls and starts the verified digest, so run it only where you intend to execute that release. It requires registry access and GitHub authentication for attestation verification. Its commands and flags are in the [verifier source](../tests/host/test-published-image.py), [Sigstore verification instructions](https://docs.sigstore.dev/quickstart/quickstart-ci/), and [GitHub verification reference](https://cli.github.com/manual/gh_attestation_verify). The launcher does not perform these checks automatically.
