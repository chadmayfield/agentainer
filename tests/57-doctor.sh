#!/bin/sh
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"
repo=$(cd "$(dirname "$0")/.." && pwd)
name="cx-doctor-$$"
# A local source overlay exercises this command without rebuilding an older image.
set --
if [ -n "${CX_TEST_DOCTOR:-}" ]; then
	set -- -v "$CX_TEST_DOCTOR:/usr/local/bin/agentainer-doctor:ro"
fi
for mode in ephemeral persist; do
	# A fresh writable container home needs no personal volume or credentials.
	out=$(run_in "$@" --name "$name-$mode" --network none -e PYTHONDONTWRITEBYTECODE=1 \
		-e "AGENTAINER_TOOLS=$mode" -v "$repo/tests/fixtures/check-doctor.py:/fixtures/check-doctor.py:ro" \
		-- python3 /fixtures/check-doctor.py 2>&1)
	rc=$?
	assert_eq "offline diagnostics preserve home files in $mode mode" 0 "$rc"
	if [ "$rc" = 0 ]; then
		assert_contains "doctor checks completed in $mode mode" DOCTOR_VERIFIED "$out"
	else
		printf '%s\n' "$out"
	fi
done
finish
