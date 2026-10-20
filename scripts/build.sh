#!/bin/sh
# Builds the Agentainer image with the pins in versions.env.
# Usage: scripts/build.sh [--platform linux/amd64] [--tag name] [--uid N] [--gid N]
set -eu
cd "$(dirname "$0")/.."
RUNTIME=${RUNTIME:-podman}
platform=""
tag="localhost/agentainer:dev"
uid=1000
gid=1000
while [ "$#" -gt 0 ]; do
	case "$1" in
	--platform)
		platform=$2
		shift 2
		;;
	--tag)
		tag=$2
		shift 2
		;;
	--uid)
		uid=$2
		shift 2
		;;
	--gid)
		gid=$2
		shift 2
		;;
	*)
		echo "build.sh: unknown option $1" >&2
		exit 2
		;;
	esac
done
# Always name the platform. Without it, a build after a cross-arch build can reuse
# the other architecture's base image from local storage.
if [ -z "$platform" ]; then
	case "$(uname -m)" in
	arm64 | aarch64) platform=linux/arm64 ;;
	x86_64 | amd64) platform=linux/amd64 ;;
	*)
		echo "build.sh: unknown host architecture $(uname -m); pass --platform" >&2
		exit 2
		;;
	esac
fi
base=$(sed -n 's/^BASE_IMAGE=//p' versions.env)
snapshot=$(sed -n 's/^APT_SNAPSHOT=//p' versions.env)
epoch=$(sed -n 's/^SOURCE_DATE_EPOCH=//p' versions.env)
if [ -z "$base" ] || [ -z "$snapshot" ] || [ -z "$epoch" ]; then
	echo "build.sh: BASE_IMAGE, APT_SNAPSHOT and SOURCE_DATE_EPOCH must be set in versions.env" >&2
	exit 1
fi
# Each pin that a Containerfile stage declares with ARG becomes a build argument. Pins
# the image does not use (CI and Kubernetes images) are left out. versions.env values
# contain no quotes or spaces, so each line is one argument.
args=$(sed -n 's/^ARG \([A-Z0-9_]*\).*/\1/p' Containerfile)
set --
while IFS= read -r line; do
	case "$line" in
	'' | '#'*) continue ;;
	esac
	if printf '%s\n' "$args" | grep -qx "${line%%=*}"; then
		set -- "$@" --build-arg "$line"
	fi
done <versions.env
# Podman's default OCI format drops the Containerfile's SHELL instruction, so RUN
# steps would run under dash without pipefail. The docker format keeps it.
# --rewrite-timestamp sets file times in every layer to no later than SOURCE_DATE_EPOCH,
# so a tool whose inputs did not change produces a byte-identical layer. Podman added
# both options in 5.6. With a remote client, the server's version is what counts: an
# older server ignores the options without an error.
if [ "$RUNTIME" = podman ]; then
	set -- "$@" --format docker
	server=$("$RUNTIME" info --format '{{.Version.Version}}' 2>/dev/null || true)
	major=${server%%.*}
	minor=${server#*.}
	minor=${minor%%.*}
	case "$major.$minor" in
	[0-9]*.[0-9]*) ;;
	*) major=0 minor=0 ;;
	esac
	if [ "$major" -gt 5 ] || { [ "$major" -eq 5 ] && [ "$minor" -ge 6 ]; }; then
		set -- "$@" --source-date-epoch "$epoch" --rewrite-timestamp
	else
		echo "build.sh: Podman server ${server:-of unknown version} is older than 5.6, so layer file times are not fixed and unchanged tools get new layer digests" >&2
	fi
fi
set -x
"$RUNTIME" build -f Containerfile ${platform:+--platform "$platform"} "$@" \
	--build-arg AGENT_UID="$uid" --build-arg AGENT_GID="$gid" \
	--build-arg IMAGE_VERSION="${IMAGE_VERSION:-dev}" \
	--build-arg VCS_REF="$(git rev-parse HEAD 2>/dev/null || echo unknown)" \
	--build-arg BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
	-t "$tag" .
