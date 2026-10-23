#!/bin/sh
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"
repo=$(cd "$(dirname "$0")/.." && pwd)
out=$(run_in --name "cx-infrastructure-$$" --pull=never --network none \
	-e PYTHONDONTWRITEBYTECODE=1 \
	-v "$repo/tests/fixtures/check-infrastructure.py:/fixtures/check-infrastructure.py:ro" \
	-- python3 /fixtures/check-infrastructure.py 2>&1)
rc=$?
assert_eq "pinned kubectl and Helm render offline and reject broken input" 0 "$rc"
if [ "$rc" = 0 ]; then
	assert_contains "infrastructure fixture completed" INFRASTRUCTURE_VERIFIED "$out"
else
	printf '%s\n' "$out"
fi
finish
