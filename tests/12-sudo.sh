#!/bin/sh
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"

assert_eq "raw image permits container sudo" "0" "$(run_in --network none -- sudo -n id -u)"
# shellcheck disable=SC2016 # expands inside the container
assert_eq "no-new-privileges blocks sudo" "SUDO_BLOCKED" \
	"$(run_in --network none --security-opt no-new-privileges=true -- sh -c 'if sudo -n true 2>/dev/null; then echo SUDO_ALLOWED; else echo SUDO_BLOCKED; fi')"
# Startup warns when sudo works, for a long-running start (AGENTAINER_QUIET=0) and for a
# one-shot command (AGENTAINER_QUIET=1), and says nothing about it under no-new-privileges.
# The credential summary proves the steps ran.
assert_contains "startup warns when sudo works" "sudo works in this container" \
	"$(run_in --network none -e AGENTAINER_QUIET=0 -- true 2>&1)"
assert_absent "no sudo warning under no-new-privileges" \
	"$(run_in --network none --security-opt no-new-privileges=true -e AGENTAINER_QUIET=0 -- true 2>&1)" \
	"credential variables" "sudo works"
assert_contains "one-shot commands also get the sudo warning" "sudo works in this container" \
	"$(run_in --network none -- sh -c 'echo STARTED' 2>&1)"

# sudo drops NPM_CONFIG_PREFIX, so root's npm uses the prefix from npm's builtin config.
repo=$(cd "$(dirname "$0")/.." && pwd)
fixtures="$repo/tests/fixtures:/fixtures:ro"
assert_eq "agent npm prefix is the tools root" "/var/lib/agentainer/active/npm" "$(run_in --network none -- npm config get prefix)"
assert_eq "sudo npm prefix is /usr/local" "/usr/local" "$(run_in --network none -- sudo -n npm config get prefix)"
# shellcheck disable=SC2016 # expands inside the container
assert_eq "sudo npm -g installs into /usr/local/bin" "/usr/local/bin/fixture-npm fixture-npm ok" \
	"$(run_in --network none -v "$fixtures" -- sh -c 'fx=$(bash /fixtures/make-tools.sh) && sudo -n npm install -g --offline --no-fund --no-audit "$fx/fixture.tgz" >/dev/null 2>&1; test -x /usr/local/bin/fixture-npm && echo "/usr/local/bin/fixture-npm $(/usr/local/bin/fixture-npm)"')"
finish
