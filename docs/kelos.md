# Kelos variant

The Kelos variant is a second image, built from [`Containerfile.kelos`](../Containerfile.kelos) on top of a published Agentainer image. It runs the Claude Code and Codex agents under [Kelos](https://github.com/kelos-dev/kelos), which starts agent containers as UID 61100 with `/kelos_entrypoint.sh`. Provenance and changes to the upstream files are in [`rootfs-kelos/SOURCE.md`](../rootfs-kelos/SOURCE.md).

## Contents

- [What it adds](#what-it-adds)
- [Environment rules](#environment-rules)
- [Push sidecar](#push-sidecar)
- [Building and testing](#building-and-testing)
- [Pins](#pins)

## What it adds

| Path in the image | What it is |
|---|---|
| `/kelos_entrypoint.sh` | Dispatcher written for this image. It runs the Kelos entrypoint for `KELOS_AGENT_TYPE` (`claude-code` or `codex`) and refuses a Claude pod that sets another Claude authentication source, such as `ANTHROPIC_API_KEY` or a cloud-provider selector, or a settings file with a credential helper. Claude's credential is `CLAUDE_CODE_OAUTH_TOKEN`. |
| `/kelos_entrypoint_claude.sh`, `/kelos_entrypoint_codex.sh` | Kelos v0.62.0 entrypoints. The Codex one carries six marked changes listed in `SOURCE.md`. |
| `/kelos/kelos-capture` | Built from source from a `v<version>-rest.<n>` tag of the fork at github.com/chadmayfield/kelos, not the upstream binary. It lists pull requests over the GitHub REST API instead of GraphQL ([Pins](#pins)). |
| `/usr/local/bin/gh` | Kelos's gh wrapper, which reads the token from `KELOS_GITHUB_TOKEN_FILE`. The real `gh` moves to `/usr/bin/gh`. |
| `/usr/local/bin/push-sidecar` | Pushes the agent's work to a branch while a Task runs, as a sidecar container ([Push sidecar](#push-sidecar)) |
| `/usr/local/lib/kelos/` | The guard, a `claude` wrapper and the MCP header helper |

Other differences from the main image:

- It runs as user `kelos` (UID 61100) with home `/home/kelos`. Tool install locations (`GOBIN`, `NPM_CONFIG_PREFIX`, `CARGO_INSTALL_ROOT`, uv and pipx) point into that home, because the Agentainer entrypoint does not run.
- The entrypoint is `tini -g -- /kelos_entrypoint.sh`, and the image has no health check.
- It adds no apt packages.
- It refuses Kelos's `KELOS_MCP_SERVERS` and reads one MCP server from files mounted at `/etc/agentainer/mcp`. `SOURCE.md` describes the rules.
- Its OCI labels (`org.opencontainers.image.version`, `revision`, `created`, `title`, `base.name`) describe the variant, not the Agentainer image it is built on.

## Environment rules

- Claude starts under `env -i` with only the variables in `claude_env_allowlist` in [`rootfs-kelos/kelos_guard.sh`](../rootfs-kelos/kelos_guard.sh): process identity, locale and terminal, `CLAUDE_CODE_OAUTH_TOKEN`, the proxy variables, the CA variables, the GitHub token variables Kelos sets, the Kelos branch variables, the git identity and the image's tool locations. Any other variable the Task sets, such as `GOPROXY`, `GOPRIVATE`, `GOFLAGS`, `NPM_CONFIG_REGISTRY`, `PIP_INDEX_URL` or `KUBECONFIG`, does not reach Claude or the commands it runs. Codex gets the whole pod environment.
- A proxy CA comes in only as `PROXY_CA_FILE`: an absolute path to a PEM file outside `/workspace`, also after symlinks are resolved. The dispatcher builds a bundle of the system CAs plus that CA and sets `GIT_SSL_CAINFO`, `SSL_CERT_FILE` and `NODE_EXTRA_CA_CERTS`. A pod that sets `GIT_SSL_CAINFO`, `GIT_SSL_CAPATH`, `SSL_CERT_FILE`, `SSL_CERT_DIR` or `NODE_EXTRA_CA_CERTS` itself is refused with exit 78.
- `HOME` must be `/home/kelos`, and `PATH` must start with the image's `PATH`, with no empty, relative, `.` or `..` entry and no newline.
- Tasks can share a Codex home volume (`/home/kelos/.codex`). Each Codex run takes an exclusive `flock` on `.agentainer-codex.lock` in it, so a second run on the same volume waits until the first one ends.

## Push sidecar

`push-sidecar` runs in its own container of the Task pod (an init container with `restartPolicy: Always`). It commits the agent's uncommitted work as "agent WIP" and pushes `HEAD` to a branch every `PUSH_INTERVAL` seconds, and once more within 20 s of SIGTERM. The header of [`push-sidecar`](../rootfs-kelos/usr/local/bin/push-sidecar) lists its environment variables. `PUSH_URL`, `PUSH_BRANCH`, `KELOS_GITHUB_TOKEN_FILE`, `GIT_AUTHOR_NAME` and `GIT_AUTHOR_EMAIL` are required.

- `PUSH_URL` must be `https://github.com/<owner>/<repo>.git`. Other hosts, including GitHub Enterprise Server, are not supported.
- Every change to a file that `HEAD` has goes into the WIP commit, whatever its name.
- A new file whose name, or the name of a directory above it, matches a pattern in [`excludes`](../rootfs-kelos/usr/local/share/push-sidecar/excludes) (`.env`, `*.pem`, `id_rsa*` and others) stays out, also when the agent staged it or the repository's `.gitignore` negates the pattern. A `push-note:` line names each such file, and the file stays in the work tree.
- A new or changed file over 10 MB stays out, and a `push-note:` line names it.
- A change of the commit a submodule points to is not committed, because `git add` would run `git status` inside the submodule, where the submodule's own config applies.
- The image has no git-lfs, so a file that `.gitattributes` sends through the LFS filter is committed as a plain file, not as an LFS pointer.
- Commits the agent made itself are pushed as they are. A rule on the remote side, such as push protection, is the only guard for them.
- Each attempt prints `push-ok` or `push-failed: <reason>`. A step that fails, such as `git status`, gives `push-failed`, also when `HEAD` itself was pushed.

## Building and testing

```sh
scripts/build.sh --variant kelos                                   # tag localhost/agentainer-kelos:dev
scripts/build.sh --variant kelos --from localhost/agentainer:dev   # on another base image
IMAGE=localhost/agentainer-kelos:dev sh tests/kelos/test_image.sh
```

- Without `--from`, the build uses the Agentainer release pinned by tag and digest in `Containerfile.kelos`.
- `--tag` sets another tag. `RUNTIME=docker` builds with Docker. `--uid`, `--gid` and `--strict-apt` apply to the main image only and are refused with `--variant kelos`.
- The `kelos-capture` stage needs network access to github.com and the Go module proxy.
- The tests need no network. They check the user, the entrypoints, the agent binaries, the gh wrapper, the credential guard and the push sidecar.

CI does not build or test the variant, and no release publishes it.

## Pins

The variant's four pins are `ARG` lines in `Containerfile.kelos`, not entries in `versions.env`, because only this build uses them:

| Pin | Value | Source the scheduled update reads |
|---|---|---|
| `AGENTAINER_IMAGE` | The newest published Agentainer release, by tag and index digest | GitHub releases of chadmayfield/agentainer, and the image index in ghcr.io |
| `GOLANG_IMAGE` | The official golang image for the newest stable Go, by tag and index digest | go.dev and Docker Hub |
| `KELOS_FORK_COMMIT` | The commit of the highest `v<version>-rest.<n>` tag of the fork, after peeling an annotated tag | The fork's tags |
| `KELOS_CAPTURE_VERSION` | That tag's name; kelos-capture reports it as its version | The fork's tags |

The scheduled update (`scripts/bump_versions.py`, resolver `r_kelos`) rewrites these lines, and its pull request then asks for a build and test run of the variant before merging. `AGENTAINER_IMAGE` uses the same release as the `AGENTAINER_RELEASE_VERSION` pin. A fork tag must be at least 72 hours old, counted from the later of the upstream release and the fork commit; when the highest tag is younger, the next one that is old enough is pinned, and when none is, or that one sorts below the current pin, the fork pins stay ([Minimum release age](versions.md#minimum-release-age)). `r_kelos` keeps all four pins and reports a failure, while the other resolvers still write theirs, when the fork's tag needs a newer Go than the newest release, when an image pin would move back, or when the tag's copies of the Kelos files in `rootfs-kelos/` differ from the files here (`SOURCE.md` lists them).

The fork exists because upstream kelos-capture lists pull requests with `gh pr list`, which uses the GitHub GraphQL API, and some HTTP egress proxies block GraphQL while they allow the REST API. Each `v<version>-rest.<n>` tag is upstream kelos-dev/kelos at release `v<version>` plus one commit that lists them with `gh api repos/<owner>/<repo>/pulls` instead. To build the upstream code, change the git remote in the `kelos-capture` stage of `Containerfile.kelos` to `https://github.com/kelos-dev/kelos.git`, set `KELOS_FORK_COMMIT` and `KELOS_CAPTURE_VERSION` to an upstream release's commit and tag, and remove `r_kelos` from `RESOLVERS` in `scripts/bump_versions.py`, because it reads only the fork's tags.
