#!/bin/sh
# Preserve the upstream skill and license from one checksum-pinned commit.
set -eu
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
trap 'exit 130' INT TERM
base="https://raw.githubusercontent.com/cursor/plugins/${UNSLOP_COMMIT:?}/pstack"
fetch=/usr/local/lib/agentainer-build/fetch.sh
dest=/usr/local/share/agentainer/skills/unslop
sh "$fetch" "$base/skills/unslop/SKILL.md" sha256 "${UNSLOP_SHA256:?}" "$work/SKILL.md"
sh "$fetch" "$base/LICENSE" sha256 "${UNSLOP_LICENSE_SHA256:?}" "$work/LICENSE"
install -d -m 0755 "$dest"
install -m 0644 "$work/SKILL.md" "$work/LICENSE" "$dest/"
