#!/bin/sh
# Runs shellcheck and shfmt from the built image over every shell file in the repo.
set -eu
cd "$(dirname "$0")/.."
RUNTIME=${RUNTIME:-podman}
IMAGE=${IMAGE:-localhost/agentbox:dev}
# shellcheck disable=SC2016 # the script runs in the container's bash
"$RUNTIME" run --rm -v "$PWD:/src:ro" -w /src --entrypoint bash "$IMAGE" -c '
set -euo pipefail
files=()
while IFS= read -r f; do
	if head -n1 "$f" | grep -Eq "^#!.*[/ ](ba)?sh([[:space:]]|$)"; then files+=("$f"); fi
done < <(find bin build scripts tests deploy rootfs/usr/local/bin -type f 2>/dev/null)
shellcheck -x "${files[@]}"
shfmt -d "${files[@]}"
steps=rootfs/usr/local/lib/agentbox/entrypoint.d
if [ -d "$steps" ]; then
	shellcheck -x -s sh "$steps"/*.sh
	shfmt -d "$steps"
fi
echo "lint ok"'
