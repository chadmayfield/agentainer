#!/bin/sh
# shellcheck disable=SC2086 # H holds "-v vol:/home/agent" on purpose
# shellcheck disable=SC2016 # single-quoted scripts expand in the container
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"
VOL="agentainer-test-home-$$"
name="agentainer-test-$$"
"$RUNTIME" volume create "$VOL" >/dev/null
cleanup() {
	"$RUNTIME" rm -f "$name" >/dev/null 2>&1
	"$RUNTIME" volume rm -f "$VOL" >/dev/null 2>&1
}
trap cleanup EXIT
# dash skips the EXIT trap on a signal; exiting from the signal trap runs it.
trap 'exit 130' INT TERM
H="-v $VOL:/home/agent"

# No credentials at all.
out=$(run_in $H -- sh -c 'claude --version && codex --version && opencode --version && agy --version && echo ALL-STARTED' 2>&1)
assert_contains "all agents start with no credentials" "ALL-STARTED" "$out"
assert_absent "one-shot commands print no startup log" "$(run_in $H -- echo STARTED 2>&1)" STARTED "agentainer:"
run_bg "$name" -v "$VOL:/home/agent"
# Step 9 logs the summary last, so wait until it appears.
if wait_for 30 sh -c '"$1" logs "$2" 2>&1 | grep -q "credential variables"' sh "$RUNTIME" "$name"; then
	pass "a long-running container finished its startup steps"
else
	fail "a long-running container finished its startup steps"
fi
assert_contains "a long-running container logs the credential summary" "no credential variables set" "$("$RUNTIME" logs "$name" 2>&1)"
"$RUNTIME" rm -f "$name" >/dev/null

FAKE=ghp_agentainertestnotreal
out=$(run_in $H -e AGENTAINER_QUIET=0 -e GH_TOKEN=$FAKE -e GIT_AUTHOR_NAME="Test User" -e GIT_AUTHOR_EMAIL=test@example.com -- \
	sh -c 'git config --global --get-regexp "credential.*helper"; git config --global user.name; git config --global user.email' 2>&1)
assert_contains "gh is the git credential helper" "gh auth git-credential" "$out"
assert_contains "identity name from env" "Test User" "$out"
assert_contains "identity email from env" "test@example.com" "$out"
assert_contains "names GH_TOKEN" "credential variables set: GH_TOKEN" "$out"
assert_absent "never prints credential values" "$out" "credential variables set" "$FAKE"
assert_eq "no duplicate helper lines on a second start" "2" \
	"$(run_in $H -e GH_TOKEN=$FAKE -- sh -c 'git config --global --get-all credential.https://github.com.helper | wc -l | tr -d " "' 2>/dev/null)"

# GITHUB_TOKEN alone also sets up git (gh reads GH_TOKEN, then GITHUB_TOKEN).
"$RUNTIME" volume rm -f "$VOL" >/dev/null
"$RUNTIME" volume create "$VOL" >/dev/null
assert_contains "GITHUB_TOKEN alone sets up git" "gh auth git-credential" \
	"$(run_in $H -e GITHUB_TOKEN=$FAKE -- git config --global --get-regexp 'credential.*helper' 2>/dev/null)"

# Hostile values never run and never print.
out=$(run_in $H -e AGENTAINER_QUIET=0 -e 'OPENAI_API_KEY=$(touch /tmp/pwned) `id` "x"' -- sh -c 'test -e /tmp/pwned && echo PWNED; echo RAN' 2>&1)
assert_absent "hostile values are not run or printed" "$out" RAN PWNED "touch /tmp"

assert_contains "warns about empty variables" "set but empty" "$(run_in $H -e GIT_AUTHOR_NAME= -- true 2>&1)"
run_in $H -e GIT_AUTHOR_NAME="Test User" -- true >/dev/null 2>&1
assert_eq "identity not overwritten" "Test User" "$(run_in $H -e GIT_AUTHOR_NAME=Other -- git config --global user.name 2>/dev/null)"
assert_contains "warns when env identity differs from gitconfig" "differs from git config" "$(run_in $H -e GIT_AUTHOR_NAME=Other -- true 2>&1)"
assert_eq "opencode uses private servers" "true" "$(run_in $H -- opencode service get disabled 2>/dev/null | tr -d '[:space:]')"

# A whitespace-only identity counts as unset and never reaches ~/.gitconfig.
assert_eq "whitespace-only identity is not written" "END" \
	"$(run_in -e "GIT_AUTHOR_NAME=   " -e "GIT_AUTHOR_EMAIL= 	" -- sh -c 'git config --global user.name; git config --global user.email; echo END' 2>/dev/null)"
assert_contains "whitespace-only identity warns as empty" "set but empty" "$(run_in -e "GIT_AUTHOR_NAME=   " -- true 2>&1)"

# The OpenCode step never overrides a service.json the user already has, even when its
# marker in ~/.agentainer is missing.
"$RUNTIME" volume rm -f "$VOL" >/dev/null
"$RUNTIME" volume create "$VOL" >/dev/null
run_in $H --network none --entrypoint sh -- -c 'opencode service set disabled false' >/dev/null 2>&1
assert_eq "opencode: an existing service.json is kept" "false" "$(run_in $H --network none -- opencode service get disabled 2>/dev/null | tr -d '[:space:]')"
run_in $H --network none -- sh -c 'opencode service set disabled false; rm -f ~/.agentainer/.opencode-service-disabled' >/dev/null 2>&1
assert_eq "opencode: kept after the marker is removed" "false" "$(run_in $H --network none -- opencode service get disabled 2>/dev/null | tr -d '[:space:]')"

finish
