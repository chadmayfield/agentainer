#!/bin/sh
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"
repo=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck disable=SC2016 # HOME expands in the container.
out=$(run_in --name "cx-defaults-$$" --network none -v "$repo/tests/fixtures:/fixtures:ro" --entrypoint sh -- -c 'HOME=$(mktemp -d /tmp/cx-defaults.XXXXXX) && export HOME && exec agentainer-entrypoint python3 /fixtures/check-defaults.py' 2>&1)
rc=$?
assert_eq "default configurations work on a fresh home" 0 "$rc"
if [ "$rc" = 0 ]; then
	assert_contains "default configuration checks completed" DEFAULTS_VERIFIED "$out"
else
	printf '%s\n' "$out"
fi
finish
