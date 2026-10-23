#!/bin/sh
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"
repo=$(cd "$(dirname "$0")/.." && pwd)
out=$(run_in --network none -v "$repo/tests/fixtures:/fixtures:ro" -- python3 /fixtures/check-abtop.py 2>&1)
rc=$?
assert_eq "abtop offline version and snapshots" 0 "$rc"
if [ "$rc" = 0 ]; then
	assert_contains "abtop checks completed" ABTOP_VERIFIED "$out"
else
	printf '%s\n' "$out"
fi
finish
