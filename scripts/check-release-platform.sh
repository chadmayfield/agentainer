#!/bin/sh
# Check the exact pushed image on its native runner before publishing its digest artifact.
# Pull flags: https://docs.docker.com/reference/cli/docker/image/pull/
# Run flags: https://docs.docker.com/reference/cli/docker/container/run/
set -eu
ref=${1:?image digest reference required}
arch=${2:?architecture required}
sha=${3:?source commit required}
version=${4:?release version required}
RUNTIME=${RUNTIME:-docker}
case "$(uname -m):$arch" in
x86_64:amd64 | aarch64:arm64 | arm64:arm64) ;;
*)
	echo "release platform: runner is not native $arch" >&2
	exit 1
	;;
esac
case "$ref" in
*@sha256:*) ;;
*)
	echo "release platform: image must be addressed by digest" >&2
	exit 1
	;;
esac
"$RUNTIME" pull --platform "linux/$arch" "$ref"
metadata=$("$RUNTIME" image inspect --format '{{.Architecture}}|{{index .Config.Labels "org.opencontainers.image.revision"}}|{{index .Config.Labels "org.opencontainers.image.version"}}' "$ref")
if [ "$metadata" != "$arch|$sha|$version" ]; then
	echo "release platform: architecture, revision or version does not match the release" >&2
	exit 1
fi
# shellcheck disable=SC2016 # id runs inside the published image.
"$RUNTIME" run --rm --pull=never --platform "linux/$arch" --name "cx-release-$arch" --network none "$ref" sh -ec '
test "$(id -u)" -ne 0
test -f /var/lib/agentainer/ready
claude --version
codex --version
agy --version
opencode --version'
