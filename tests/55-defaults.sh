#!/bin/sh
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"
repo=$(cd "$(dirname "$0")/.." && pwd)
name="cx-defaults-$$"
volume="cx-defaults-home-$$-$(date +%s)"
if ! "$RUNTIME" volume create "$volume" >/dev/null; then
	fail "create a fresh defaults home volume"
	finish
	exit 1
fi
trap '"$RUNTIME" rm -f "$name" >/dev/null 2>&1; "$RUNTIME" volume rm "$volume" >/dev/null 2>&1' EXIT
trap 'exit 130' INT TERM
out=$(run_in --name "$name" --network none -v "$volume:/home/agent" -v "$repo/tests/fixtures:/fixtures:ro" -- python3 /fixtures/check-defaults.py 2>&1)
rc=$?
assert_eq "default configurations work on a fresh home" 0 "$rc"
if [ "$rc" = 0 ]; then
	assert_contains "default configuration checks completed" DEFAULTS_VERIFIED "$out"
else
	printf '%s\n' "$out"
fi
finish
