# Versions, updates and releases

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

Each release publishes `ghcr.io/chadmayfield/agentainer` for amd64 and arm64:

- tagged with the version and `sha-<commit>`, with `latest` reserved for stable releases;
- signed with cosign keyless signing, the index and each architecture's image;
- with an SBOM and provenance attestation, and zstd-compressed layers.

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

Release publishing waits for the aggregate CI check, including both architecture builds and clean-layer comparisons. The release script runs [`tests/host/test-published-image.py`](../tests/host/test-published-image.py) against the signed index digest before moving the version or `latest` tags and before creating the GitHub release. A verification failure leaves those public tags unchanged. It verifies the index and both platform signatures with the exact build workflow identity and GitHub OIDC issuer ([Sigstore CI verification](https://docs.sigstore.dev/quickstart/quickstart-ci/)). It checks for SBOM and provenance attestation descriptors bound to each platform manifest ([Docker attestation storage](https://docs.docker.com/build/metadata/attestations/attestation-storage/)), then pulls and starts the native platform using the verified index digest. Descriptor checks do not validate every field inside the attestation payloads.

This verifier runs against published artifacts during a release. A pull request exercises its success and failure cases with fixtures; live registry and keyless verification remain not verified until that release job runs.
