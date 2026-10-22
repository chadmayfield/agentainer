#!/bin/sh
# shellcheck disable=SC2086 # H deliberately holds a volume option pair
# shellcheck disable=SC2016 # expands inside the container
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"
repo=$(cd "$(dirname "$0")/.." && pwd)
volume="agentainer-test-python-$$"
"$RUNTIME" volume create "$volume" >/dev/null
trap '"$RUNTIME" volume rm -f "$volume" >/dev/null' EXIT
trap 'exit 130' INT TERM
H="-v $volume:/home/agent"
if ! run_in $H --network none --security-opt no-new-privileges=true -e AGENTAINER_TOOLS=persist \
	-v "$repo/tests/fixtures/plant-python-site.py:/fixtures/plant-python-site.py:ro" \
	-- python3 -I /fixtures/plant-python-site.py; then
	fail "Python isolation fixture was planted"
	finish
	exit 1
fi
out=$(run_in $H --network none --security-opt no-new-privileges=true -e AGENTAINER_TOOLS=persist -- sh -ec '
test ! -e "$HOME/auto-python-executed"
agentainer-doctor --json >/dev/null
agentainer-mcp sync
test ! -e "$HOME/auto-python-executed"
python3 -c "pass"
test -f "$HOME/auto-python-executed"
echo PYTHON_ISOLATION_VERIFIED' 2>&1)
rc=$?
assert_eq "image helpers ignore persisted Python startup code" 0 "$rc"
if [ "$rc" = 0 ]; then
	assert_contains "user Python keeps its intentional user site" PYTHON_ISOLATION_VERIFIED "$out"
else
	printf '%s\n' "$out"
fi
finish
