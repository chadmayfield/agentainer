#!/bin/sh
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"

assert_eq "raw image permits container sudo" "0" "$(run_in --network none -- sudo -n id -u)"
# shellcheck disable=SC2016 # expands inside the container
assert_eq "no-new-privileges blocks sudo" "SUDO_BLOCKED" \
	"$(run_in --network none --security-opt no-new-privileges=true -- sh -c 'if sudo -n true 2>/dev/null; then echo SUDO_ALLOWED; else echo SUDO_BLOCKED; fi')"
finish
