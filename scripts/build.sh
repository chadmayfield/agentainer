#!/bin/sh
# Builds the AgentBox image with the pins in versions.env.
# Usage: scripts/build.sh [--platform linux/amd64] [--tag name] [--uid N] [--gid N]
set -eu
cd "$(dirname "$0")/.."
RUNTIME=${RUNTIME:-podman}
platform=""
tag="localhost/agentbox:dev"
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
if [ -z "$base" ] || [ -z "$snapshot" ]; then
	echo "build.sh: BASE_IMAGE and APT_SNAPSHOT must be set in versions.env" >&2
	exit 1
fi
# Podman's default OCI format drops the Containerfile's SHELL instruction, so RUN
# steps would run under dash without pipefail. The docker format keeps it.
format=""
if [ "$RUNTIME" = podman ]; then format="--format docker"; fi
set -x
# shellcheck disable=SC2086 # $format is empty or two words on purpose
"$RUNTIME" build $format -f Containerfile ${platform:+--platform "$platform"} \
	--build-arg BASE_IMAGE="$base" --build-arg APT_SNAPSHOT="$snapshot" \
	--build-arg UID="$uid" --build-arg GID="$gid" \
	--build-arg IMAGE_VERSION="${IMAGE_VERSION:-dev}" \
	--build-arg VCS_REF="$(git rev-parse HEAD 2>/dev/null || echo unknown)" \
	--build-arg BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
	-t "$tag" .
