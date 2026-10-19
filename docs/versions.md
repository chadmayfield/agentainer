# Versions, updates and releases

## Pinned inputs

[`versions.env`](../versions.env) pins every input of the image: the base image digest, the apt snapshot date, each agent and tool version, and the checksum of every download. The build checks each download against it. The one exception is the Rust toolchain: `rustup-init` downloads the components and checks each against the hashes in Rust's own channel manifest.

Claude Code is the native binary from Anthropic's release host, the file Anthropic's native installer downloads. The weekly update checks the release's `manifest.json` against Anthropic's GPG signature before it pins the binary's SHA-256 ([binary integrity](https://code.claude.com/docs/en/setup#binary-integrity-and-code-signing)).

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

## Weekly update

Every Monday, [`.github/workflows/bump.yml`](../.github/workflows/bump.yml) resolves the newest upstream versions with [`scripts/bump_versions.py`](../scripts/bump_versions.py) and opens a pull request against `develop`. It refuses to write any value that does not match the expected format for its pin. The pull request's build page shows which pins changed. A maintainer reviews and merges it by hand, and nothing is published until the next release.

The workflow opens the pull request with a GitHub App token when the repository has the variable `BUMP_APP_CLIENT_ID` and the secret `BUMP_APP_PRIVATE_KEY`; CI then starts on its own. Without them it uses `GITHUB_TOKEN`, and GitHub holds the pull request's CI until a maintainer chooses "Approve workflows to run" ([CONTRIBUTING.md](../CONTRIBUTING.md#the-bump-github-app) describes the App).

## Releases

Releases are calendar versions, `YYYY.MM.DD`, with `.N` for a second release on the same day. Each release publishes `ghcr.io/chadmayfield/agentainer` for amd64 and arm64:

- tagged `latest`, the version and `sha-<commit>`;
- signed with cosign keyless signing, the index and each architecture's image;
- with an SBOM and provenance attestation, and zstd-compressed layers.

A runtime needs zstd support to pull the image. These are the first versions with it:

| Runtime | First version that pulls zstd layers |
|---|---|
| Docker Engine | 23.0.0 ("Add support for pulling `zstd` compressed layers", [Engine 23.0 release notes](https://docs.docker.com/engine/release-notes/23.0/), moby/moby#41759) |
| containerd, including Kubernetes nodes that use it | 1.5.0 ("Add support for layers compressed with zstd", [containerd v1.5.0 release notes](https://github.com/containerd/containerd/releases/tag/v1.5.0)) |
| Podman | Not verified. Podman's release notes do not name a version. containers/image added zstd in containers/image#639, and Podman 1.6.2 is the first release whose `go.mod` uses a containers/image version with that change. |

The release job refreshes `main` while holding its release lock. Only the highest calendar version in main's first-parent release merges can move `latest`. A delayed older build or retry publishes its own version tag and leaves `latest` alone. The comparison includes numeric same-day suffixes, so `.10` follows `.2` ([release script](../scripts/release-image.sh), [version comparison](../scripts/release_order.py)).

The published image is a fresh build from the release commit with the same pinned inputs, not the exact image the pull request's tests ran on.

Instructions for checking the signature with `cosign verify` will be added with the first release, once they have been run against a published image.
