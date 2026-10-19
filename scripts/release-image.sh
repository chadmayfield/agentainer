#!/bin/bash
# Publish the checked, signed index. Run only under the workflow's release lock.
set -euo pipefail
script_dir=$(cd "$(dirname "$0")" && pwd)
img=ghcr.io/chadmayfield/agentainer
# Each publish job uploads one file, named after its architecture, that holds its
# digest. Anything else in digests/ means the artifacts are not what this run pushed.
refs=()
for arch in amd64 arm64; do
	d=$(cat "digests/$arch")
	[[ $d =~ ^sha256:[0-9a-f]{64}$ ]] || {
		echo "::error::digests/$arch does not hold a digest." >&2
		exit 1
	}
	refs+=("$img@$d")
done
n=$(find digests -type f | wc -l | tr -d " ")
[ "$n" -eq 2 ] || {
	echo "::error::Expected 2 digest files, found $n." >&2
	exit 1
}
# The new index gets only the sha-<short> tag until it is checked and signed, so a
# failure here leaves latest and <version> on the last signed release.
# GHCR shows the description of a multi-arch image from the index annotations, not
# from image labels (GitHub docs, "Working with the Container registry"). No
# licenses annotation: the image bundles software under many licenses, so a single
# SPDX identifier would be wrong.
desc="Claude Code, Codex, Antigravity CLI and OpenCode in one container"
docker buildx imagetools create -t "$img:sha-${SHA::7}" \
	--annotation "index:org.opencontainers.image.description=$desc" \
	--annotation "index:org.opencontainers.image.source=https://github.com/chadmayfield/agentainer" \
	"${refs[@]}"
digest=$(docker buildx imagetools inspect "$img:sha-${SHA::7}" --format '{{json .Manifest}}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["digest"])')
[[ $digest =~ ^sha256:[0-9a-f]{64}$ ]] || {
	echo "::error::No digest for sha-${SHA::7}." >&2
	exit 1
}
# buildx drops index annotations without an error when every source manifest has a
# Docker media type, so check that they arrived.
docker buildx imagetools inspect --raw "$img@$digest" |
	DESC="$desc" python3 -c 'import json,os,sys; a=json.load(sys.stdin).get("annotations",{}); sys.exit(a.get("org.opencontainers.image.description")!=os.environ["DESC"])'
# --recursive also signs each per-architecture manifest in the index. A runtime
# that pulls the tag resolves it to the manifest for its platform, and a policy
# that checks that digest finds no signature on it when only the index is signed.
cosign sign --yes --recursive "$img@$digest"
# With one index as its only source and no annotations, imagetools create pushes
# the source's bytes unchanged (buildx util/imagetools/create.go, combine), so the
# public tags point at the digest just signed. --dry-run prints those bytes plus a
# newline; check their digest before moving the tags.
retag=$(docker buildx imagetools create --dry-run "$img@$digest" |
	python3 -c 'import hashlib,sys; b=sys.stdin.buffer.read(); print("sha256:"+hashlib.sha256(b[:-1] if b.endswith(b"\n") else b).hexdigest())')
[ "$retag" = "$digest" ] || {
	echo "::error::Re-tagging would push $retag, not the signed $digest." >&2
	exit 1
}
# Refresh main inside the release lock. The highest merged calendar version is the
# only release allowed to move latest; a delayed older build still gets its own tag.
# git-log documents --first-parent and --format: https://git-scm.com/docs/git-log
# git-fetch documents --no-tags and refspecs: https://git-scm.com/docs/git-fetch
git fetch --no-tags origin refs/heads/main
move_latest=$(git log --first-parent --format=%s FETCH_HEAD |
	python3 "$script_dir/release_order.py" "$V" "$OWNER")
set -- "$V"
if [ "$move_latest" = true ]; then
	set -- "$@" latest
else
	echo "A newer release is merged into main; keeping latest and publishing only $V."
fi
tags=()
for t; do tags+=(-t "$img:$t"); done
docker buildx imagetools create "${tags[@]}" "$img@$digest"
for t; do
	got=$(docker buildx imagetools inspect "$img:$t" --format '{{json .Manifest}}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["digest"])')
	[ "$got" = "$digest" ] || {
		echo "::error::$img:$t points at $got, not $digest." >&2
		exit 1
	}
done
