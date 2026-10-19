#!/bin/bash
# Installs Claude Code, Codex, Antigravity CLI and OpenCode v2, pinned in versions.env.
set -euo pipefail
# shellcheck source=versions.env
. /usr/local/share/agentainer/versions.env
F=/tmp/agentainer-build/fetch.sh
case "${TARGETARCH:?}" in
amd64)
	A=AMD64
	TRIPLE=x86_64
	OC=linux-x64-baseline
	;;
arm64)
	A=ARM64
	TRIPLE=aarch64
	OC=linux-arm64
	;;
*)
	echo "unsupported arch $TARGETARCH" >&2
	exit 1
	;;
esac
val() {
	local v="$1"
	printf '%s' "${!v}"
}
W=$(mktemp -d)
cd "$W"

# Claude Code: the pinned npm tarball, checked against versions.env, installed outside
# home (spec 3.1). npm fetches the platform package and checks it against registry metadata.
sh $F "https://registry.npmjs.org/@anthropic-ai/claude-code/-/claude-code-${CLAUDE_CODE_VERSION}.tgz" sri "${CLAUDE_CODE_INTEGRITY}" claude-code.tgz
npm install -g --prefix /usr/local --no-fund --no-audit ./claude-code.tgz
# Ubuntu's npm ignores the "libc" field and also installs the musl build, which glibc never uses.
rm -rf /usr/local/lib/node_modules/@anthropic-ai/claude-code/node_modules/@anthropic-ai/claude-code-linux-*-musl
claude --version >/dev/null

# Codex: the complete release package, laid out as OpenAI's installer does
# (chatgpt.com/codex/install.sh, install_package_release). The interactive CLI needs it.
sh $F "https://github.com/openai/codex/releases/download/rust-v${CODEX_VERSION}/codex-package-${TRIPLE}-unknown-linux-musl.tar.gz" sha256 "$(val "CODEX_SHA256_$A")" codex.tgz
mkdir -p /opt/codex
# As root, tar would keep the archive's owner; the install must be root-owned.
tar --no-same-owner -xzf codex.tgz -C /opt/codex
chown -R root:root /opt/codex
test -f /opt/codex/codex-package.json
chmod 0755 /opt/codex/bin/codex /opt/codex/bin/codex-code-mode-host /opt/codex/codex-path/rg
if [ -f /opt/codex/codex-resources/bwrap ]; then chmod 0755 /opt/codex/codex-resources/bwrap; fi
# The voice host (77 MB) captures audio for dictation; a container has no microphone.
# Codex starts and passes `codex doctor` without it.
rm -rf /opt/codex/codex-resources/voice
ln -sf bin/codex /opt/codex/codex
ln -sf /opt/codex/bin/codex /usr/local/bin/codex

# Antigravity CLI: tarball named in versions.env; the binary inside is "antigravity" (install.sh)
sh $F "$(val "AGY_URL_$A")" sha512 "$(val "AGY_SHA512_$A")" agy.tgz
if tar -tzf agy.tgz >/dev/null 2>&1; then
	tar -xzf agy.tgz antigravity
	install -m 0755 antigravity /usr/local/bin/agy
else
	# The official install.sh also accepts a raw binary payload (lines 154 to 163).
	install -m 0755 agy.tgz /usr/local/bin/agy
fi

# OpenCode v2: npm platform package, checked against registry integrity (spec 3.4)
sh $F "https://registry.npmjs.org/@opencode/cli-${OC}/-/cli-${OC}-${OPENCODE_VERSION}.tgz" sri "$(val "OPENCODE_INTEGRITY_$A")" opencode.tgz
tar -xzf opencode.tgz package/bin/opencode
install -m 0755 package/bin/opencode /usr/local/bin/opencode

cd /
rm -rf "$W" /root/.npm
