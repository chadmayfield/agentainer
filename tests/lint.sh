#!/bin/sh
# Runs shellcheck and shfmt from the built image over every shell file in the repo.
set -eu
cd "$(dirname "$0")/.."
RUNTIME=${RUNTIME:-podman}
IMAGE=${IMAGE:-localhost/agentainer:dev}
# shellcheck disable=SC2016 # the script runs in the container's bash
"$RUNTIME" run --rm --pull=never -v "$PWD:/src:ro" -w /src --entrypoint bash "$IMAGE" -c '
set -euo pipefail
files=()
while IFS= read -r f; do
	if head -n1 "$f" | grep -Eq "^#!.*[/ ](ba)?sh([[:space:]]|$)"; then files+=("$f"); fi
done < <(find bin build scripts tests deploy rootfs/usr/local/bin -type d -name node_modules -prune -o -type f -print 2>/dev/null)
shellcheck -x "${files[@]}"
shfmt -d "${files[@]}"
steps=rootfs/usr/local/lib/agentainer/entrypoint.d
if [ -d "$steps" ]; then
	shellcheck -x -s sh "$steps"/*.sh rootfs/usr/local/lib/agentainer/*.sh
	shfmt -d "$steps" rootfs/usr/local/lib/agentainer/*.sh
fi
shellcheck -x -s bash rootfs/etc/agentainer/home/.bashrc rootfs/etc/agentainer/home/.config/agentainer/shell-theme.bash
shfmt -ln bash -d rootfs/etc/agentainer/home/.bashrc rootfs/etc/agentainer/home/.config/agentainer/shell-theme.bash
shellcheck -x -s sh rootfs/etc/agentainer/home/.profile
shfmt -ln posix -d rootfs/etc/agentainer/home/.profile
echo "lint ok"'
