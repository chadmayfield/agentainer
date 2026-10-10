#!/bin/sh
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"

# shellcheck disable=SC2016 # expands in the container
out=$(run_in -- bash -c '
for c in ssh tmux rsync git git-lfs git-flow git-filter-repo rg fd fzf bat eza vim nano \
  ctags patch diff jq sqlite3 pgcli make gcc python3 pipx node npm shellcheck shfmt curl wget \
  http nc ip ping dig unzip zip zstd xz 7z exiftool cloc asciinema age ansible oras \
  bwrap htop tree file less sudo; do
  command -v "$c" >/dev/null 2>&1 || echo "MISSING $c"
done
echo DONE')
assert_eq "all apt tools on PATH" "DONE" "$out"
# ping needs no capability: its file capability is removed and the runtime allows
# unprivileged ICMP sockets through net.ipv4.ping_group_range.
assert_contains "ping works without NET_RAW" "1 received" \
	"$(run_in --sysctl 'net.ipv4.ping_group_range=1000 1000' -- ping -c1 -W2 127.0.0.1 2>&1)"
assert_contains "fd runs" "fd" "$(run_in -- fd --version)"
assert_contains "bat runs" "bat" "$(run_in -- bat --version)"
assert_contains "python is 3.14" "Python 3.14" "$(run_in -- python3 --version)"
assert_contains "node is 22" "v22." "$(run_in -- node --version)"
assert_contains "tmux runs" "tmux 3.6" "$(run_in -- tmux -V)"
assert_contains "pip --user is refused (PEP 668)" "externally-managed" "$(run_in -- sh -c 'python3 -m pip install --user requests 2>&1 || true')"

finish
