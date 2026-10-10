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
trap cleanup EXIT INT TERM
H="-v $VOL:/home/agent"

# Review focus 2: no credentials at all.
out=$(run_in $H -- sh -c 'claude --version && codex --version && opencode --version && agy --version && echo ALL-STARTED' 2>&1)
assert_contains "all agents start with no credentials" "ALL-STARTED" "$out"
assert_eq "one-shot commands print no startup log" "none" "$(run_in $H -- true 2>&1 | grep 'agentainer:' || echo none)"
run_bg "$name" -v "$VOL:/home/agent"
sleep 2
assert_contains "a long-running container logs the credential summary" "no credential variables set" "$("$RUNTIME" logs "$name" 2>&1)"
"$RUNTIME" rm -f "$name" >/dev/null

FAKE=ghp_agentainertestnotreal
out=$(run_in $H -e AGENTAINER_QUIET=0 -e GH_TOKEN=$FAKE -e GIT_AUTHOR_NAME="Test User" -e GIT_AUTHOR_EMAIL=test@example.com -- \
	sh -c 'git config --global --get-regexp "credential.*helper"; git config --global user.name; git config --global user.email' 2>&1)
assert_contains "gh is the git credential helper" "gh auth git-credential" "$out"
assert_contains "identity name from env" "Test User" "$out"
assert_contains "identity email from env" "test@example.com" "$out"
assert_contains "names GH_TOKEN" "credential variables set: GH_TOKEN" "$out"
case "$out" in
*"$FAKE"*) fail "never prints credential values" ;;
*) pass "never prints credential values" ;;
esac
assert_eq "no duplicate helper lines on a second start" "2" \
	"$(run_in $H -e GH_TOKEN=$FAKE -- sh -c 'git config --global --get-all credential.https://github.com.helper | wc -l | tr -d " "' 2>/dev/null)"

# GITHUB_TOKEN alone also sets up git (gh reads GH_TOKEN, then GITHUB_TOKEN).
"$RUNTIME" volume rm -f "$VOL" >/dev/null
"$RUNTIME" volume create "$VOL" >/dev/null
assert_contains "GITHUB_TOKEN alone sets up git" "gh auth git-credential" \
	"$(run_in $H -e GITHUB_TOKEN=$FAKE -- git config --global --get-regexp 'credential.*helper' 2>/dev/null)"

# Hostile values never run and never print.
out=$(run_in $H -e AGENTAINER_QUIET=0 -e 'OPENAI_API_KEY=$(touch /tmp/pwned) `id` "x"' -- sh -c 'test -e /tmp/pwned && echo PWNED; true' 2>&1)
case "$out" in
*PWNED* | *'touch /tmp'*) fail "hostile values are not run or printed" "$out" ;;
*) pass "hostile values are not run or printed" ;;
esac

assert_contains "warns about empty variables" "set but empty" "$(run_in $H -e GIT_AUTHOR_NAME= -- true 2>&1)"
run_in $H -e GIT_AUTHOR_NAME="Test User" -- true >/dev/null 2>&1
assert_eq "identity not overwritten" "Test User" "$(run_in $H -e GIT_AUTHOR_NAME=Other -- git config --global user.name 2>/dev/null)"
assert_contains "warns when env identity differs from gitconfig" "differs from git config" "$(run_in $H -e GIT_AUTHOR_NAME=Other -- true 2>&1)"
assert_eq "opencode uses private servers" "true" "$(run_in $H -- opencode service get disabled 2>/dev/null | tr -d '[:space:]')"

finish
