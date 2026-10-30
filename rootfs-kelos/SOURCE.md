# Kelos files in this directory

Source: https://github.com/kelos-dev/kelos, tag v0.62.0, commit 8b0805c6474017c0347e2f4e658f7b15e8b143db. Apache-2.0, see LICENSE.kelos. Kelos v0.62.0 has no NOTICE file.

| File here | Source | Change |
|---|---|---|
| kelos_entrypoint_claude.sh | claude-code/kelos_entrypoint.sh | none |
| kelos_entrypoint_codex.sh | codex/kelos_entrypoint.sh | five marked changes: auth.json written only when missing, created with mode 0600, the config.toml setting added only when absent, every entry in CODEX_HOME except auth.json removed at each start (lost+found included on an ext4 volume), refusing when CODEX_HOME is not /home/kelos/.codex or is a symlink, or auth.json is a symlink or not a regular file, and an existing auth.json replaced from CODEX_AUTH_JSON when it is not valid JSON, lacks the token fields, or holds another account or other credentials (AGENTAINER CHANGE, CHANGE 2, CHANGE 3, CHANGE 4, CHANGE 5) |
| agent-gh-wrapper.sh | hack/agent-gh-wrapper.sh | none |
| /kelos/kelos-capture (built in Containerfile.kelos) | Built from source from the chadmayfield/kelos fork (github.com/chadmayfield/kelos), branch proxy-env-for-git-init, commit ca909c7f6b80e9ac8ab7b8db11399e4363aa841d, on top of the v0.62.0 base commit. Not the upstream binary. | PR capture reads GitHub over REST instead of GraphQL (the egress proxy blocks GraphQL) |
| LICENSE.kelos | LICENSE | none |

kelos_entrypoint.sh (dispatcher), kelos_guard.sh and claude-wrapper.sh are not from Kelos. They are written for this image.

Build: the `kelos-capture` stage of Containerfile.kelos fetches that commit by full SHA (and checks `git rev-parse HEAD` against it), then runs `CGO_ENABLED=0 GOOS=linux GOARCH=$TARGETARCH go build -trimpath -ldflags "-X github.com/kelos-dev/kelos/internal/version.Version=v0.62.0-proxy.3" -o /out/kelos-capture ./cmd/kelos-capture` with golang 1.25.14, pinned by index digest in the Containerfile. The fork's go.mod says `go 1.25.0` and has no toolchain line.

Two builds of the same commit gave these SHA-256 values for the binary inside the image:

    8a368760f40ed99552ce441198fde9c640d010110203a13a0ac64c315a94804b  linux/amd64
    0daa73988ea31da678736ca92702ea6ca7efcb4ed10076eb96a6f1e6ef3e0c2a  linux/arm64
