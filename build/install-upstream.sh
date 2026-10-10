#!/bin/bash
# Installs upstream tools pinned in versions.env. Runs as root during the build.
set -euo pipefail
# shellcheck source=versions.env
. /usr/local/share/agentainer/versions.env
F=/tmp/agentainer-build/fetch.sh
case "${TARGETARCH:?}" in
amd64)
	A=AMD64
	TRIPLE=x86_64
	TRIVY_ARCH=64bit
	;;
arm64)
	A=ARM64
	TRIPLE=aarch64
	TRIVY_ARCH=ARM64
	;;
*)
	echo "unsupported arch $TARGETARCH" >&2
	exit 1
	;;
esac
sha() {
	local v="$1_SHA256_$A"
	printf '%s' "${!v}"
}
W=$(mktemp -d)
cd "$W"

# Go (https://go.dev/dl/)
sh $F "https://go.dev/dl/go${GO_VERSION}.linux-${TARGETARCH}.tar.gz" sha256 "$(sha GO)" go.tgz
tar -C /usr/local -xzf go.tgz

# Rust through rustup-init (https://static.rust-lang.org/rustup/archive/)
sh $F "https://static.rust-lang.org/rustup/archive/${RUSTUP_VERSION}/${TRIPLE}-unknown-linux-gnu/rustup-init" sha256 "$(sha RUSTUP)" rustup-init
chmod +x rustup-init
# rustup checks each component against the hashes in this versioned manifest; check the
# manifest itself against versions.env first.
sh $F "https://static.rust-lang.org/dist/channel-rust-${RUST_VERSION}.toml" sha256 "${RUST_MANIFEST_SHA256}" rust-manifest.toml
RUSTUP_HOME=/opt/rustup CARGO_HOME=/opt/cargo ./rustup-init -y --no-modify-path \
	--profile minimal --default-toolchain "${RUST_VERSION}" --component clippy,rustfmt
rm -rf /opt/rustup/toolchains/*/share/doc
chmod -R a+rX /opt/rustup /opt/cargo

# yq (single binary)
sh $F "https://github.com/mikefarah/yq/releases/download/v${YQ_VERSION}/yq_linux_${TARGETARCH}" sha256 "$(sha YQ)" yq
install -m 0755 yq /usr/local/bin/yq

# gh
sh $F "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${TARGETARCH}.tar.gz" sha256 "$(sha GH)" gh.tgz
tar -xzf gh.tgz
install -m 0755 "gh_${GH_VERSION}_linux_${TARGETARCH}/bin/gh" /usr/local/bin/gh

# uv and uvx
sh $F "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-${TRIPLE}-unknown-linux-gnu.tar.gz" sha256 "$(sha UV)" uv.tgz
tar -xzf uv.tgz
install -m 0755 "uv-${TRIPLE}-unknown-linux-gnu/uv" "uv-${TRIPLE}-unknown-linux-gnu/uvx" /usr/local/bin/

# trivy
sh $F "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-${TRIVY_ARCH}.tar.gz" sha256 "$(sha TRIVY)" trivy.tgz
tar -xzf trivy.tgz trivy
install -m 0755 trivy /usr/local/bin/trivy

# curlie
sh $F "https://github.com/rs/curlie/releases/download/v${CURLIE_VERSION}/curlie_${CURLIE_VERSION}_linux_${TARGETARCH}.tar.gz" sha256 "$(sha CURLIE)" curlie.tgz
tar -xzf curlie.tgz curlie
install -m 0755 curlie /usr/local/bin/curlie

# golangci-lint
G="golangci-lint-${GOLANGCI_LINT_VERSION}-linux-${TARGETARCH}"
sh $F "https://github.com/golangci/golangci-lint/releases/download/v${GOLANGCI_LINT_VERSION}/${G}.tar.gz" sha256 "$(sha GOLANGCI_LINT)" golangci.tgz
tar -xzf golangci.tgz
install -m 0755 "${G}/golangci-lint" /usr/local/bin/golangci-lint

# tea (Gitea CLI, from gitea.com)
sh $F "https://gitea.com/gitea/tea/releases/download/v${TEA_VERSION}/tea-${TEA_VERSION}-linux-${TARGETARCH}.xz" sha256 "$(sha TEA)" tea.xz
xz -d tea.xz
install -m 0755 tea /usr/local/bin/tea

cd /
rm -rf "$W"
