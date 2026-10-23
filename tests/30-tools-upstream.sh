#!/bin/sh
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"
# shellcheck source=versions.env
. "$(dirname "$0")/../versions.env"

assert_contains "go version" "go$GO_VERSION " "$(run_in -- go version)"
assert_contains "rustc version" "rustc $RUST_VERSION " "$(run_in -- rustc --version)"
assert_contains "cargo version" "cargo $RUST_VERSION " "$(run_in -- cargo --version)"
assert_eq "clippy and rustfmt installed" "rc=0" "$(run_in -- sh -c 'cargo clippy --version >/dev/null && cargo fmt --version >/dev/null; echo rc=$?')"
assert_eq "cargo builds with a run-time CARGO_HOME" "rc=0" \
	"$(run_in -e CARGO_HOME=/tmp/ch -- sh -c 'cd /tmp && cargo new -q h && cd h && cargo build -q 2>&1 && ./target/debug/h >/dev/null; echo rc=$?')"
assert_contains "yq is mikefarah" "mikefarah" "$(run_in -- yq --version)"
assert_contains "yq version" "v$YQ_VERSION" "$(run_in -- yq --version)"
assert_contains "gh version" "gh version $GH_VERSION " "$(run_in -- gh --version)"
assert_contains "uv version" "uv $UV_VERSION" "$(run_in -- uv --version)"
assert_contains "uvx version" "uvx $UV_VERSION" "$(run_in -- uvx --version)"
assert_eq "ruff version" "ruff $RUFF_VERSION" "$(run_in -- ruff --version)"
assert_contains "trivy version" "Version: $TRIVY_VERSION" "$(run_in -- trivy --version)"
assert_contains "curlie version" "curlie $CURLIE_VERSION" "$(run_in -- curlie version 2>&1)"
assert_contains "golangci-lint version" "version $GOLANGCI_LINT_VERSION " "$(run_in -- golangci-lint --version)"
assert_contains "tea version" "$TEA_VERSION" "$(run_in -- tea --version)"
# find prints END only when it exits 0, so a missing or unreadable path fails these checks
# with find's error message in the output instead of passing on an empty result.
assert_eq "everything under /opt and /usr/local is root-owned" "END" \
	"$(run_in -- sh -c 'find /opt /usr/local -xdev ! -user root ! -type l 2>&1 && echo END')"
assert_eq "nothing under /opt and /usr/local is world-writable" "END" \
	"$(run_in -- sh -c 'find /opt /usr/local -xdev -perm -o+w ! -type l 2>&1 && echo END')"
# shellcheck disable=SC2016 # expands in the container
assert_eq "no Rust docs shipped" "END" \
	"$(run_in -- sh -c 'find "$RUSTUP_HOME/toolchains" -path "*/share/doc" -prune 2>&1 && echo END')"
assert_eq "no build leftovers" "rc=2" "$(run_in -- sh -c 'ls /tmp/agentainer-build 2>/dev/null; echo rc=$?')"

# Go's own test suite and API lists are not needed to build, vet or test code.
assert_eq "no Go test suite or API lists" "none" "$(run_in -- sh -c 'ls -d /usr/local/go/test /usr/local/go/api 2>/dev/null || echo none')"

finish
