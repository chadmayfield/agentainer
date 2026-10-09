#!/bin/sh
# Builds with a non-default UID and an existing GID (20 is "dialout" in Ubuntu and
# "staff" on macOS) and checks the agent user. Slow: it builds a full image.
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/../lib.sh"
cd "$(dirname "$0")/../.." || exit 2
tag=localhost/agentbox:test-uid
if RUNTIME="$RUNTIME" sh scripts/build.sh --uid 1001 --gid 20 --tag "$tag" >/dev/null 2>&1; then
	pass "builds with --uid 1001 --gid 20"
else
	fail "builds with --uid 1001 --gid 20"
fi
IMAGE=$tag
assert_eq "uid is 1001" "1001" "$(run_in -- id -u)"
assert_eq "gid is 20" "20" "$(run_in -- id -g)"
assert_eq "user is agent" "agent" "$(run_in -- id -un)"
assert_eq "home is owned by uid 1001" "1001" "$(run_in -- stat -c %u /home/agent)"
"$RUNTIME" rmi -f "$tag" >/dev/null 2>&1
finish
