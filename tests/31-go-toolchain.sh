#!/bin/sh
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"

assert_eq "Go defaults to the bundled compiler" "local" \
	"$(run_in --network none -- go env GOTOOLCHAIN)"
assert_eq "Go automatic toolchain selection remains an explicit opt-in" "auto" \
	"$(run_in --network none -e GOTOOLCHAIN=auto -- go env GOTOOLCHAIN)"
# The future requirement must fail without attempting a compiler download.
# shellcheck disable=SC2016 # the status variable expands inside the container
out=$(run_in --network none -- sh -c '
cd /tmp && mkdir go-toolchain-check && cd go-toolchain-check || exit 1
printf "module example.com/toolchain-check\n\ngo 999.0.0\n" >go.mod
go list ./... 2>&1
rc=$?
printf "\nchecked rc=%s\n" "$rc"
')
assert_contains "newer Go requirement fails with the bundled compiler" 'GOTOOLCHAIN=local' "$out"
assert_contains "newer Go requirement returns failure" 'checked rc=1' "$out"
assert_absent "newer Go requirement does not download a compiler" "$out" 'checked rc=' 'downloading go'
finish
