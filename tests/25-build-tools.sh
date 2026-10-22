#!/bin/sh
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"
repo=$(cd "$(dirname "$0")/.." && pwd)
out=$(run_in --name "cx-build-tools-$$" --network none \
	-e PYTHONDONTWRITEBYTECODE=1 \
	-v "$repo/tests/fixtures/check-build-tools.py:/fixtures/check-build-tools.py:ro" \
	-- python3 /fixtures/check-build-tools.py 2>&1)
rc=$?
assert_eq "native builds, dependency metadata and PostgreSQL client checks" 0 "$rc"
if [ "$rc" = 0 ]; then
	assert_contains "build tool fixture completed" BUILD_TOOLS_VERIFIED "$out"
else
	printf '%s\n' "$out"
fi
finish
