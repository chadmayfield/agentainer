#!/bin/sh
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"

assert_eq "user is agent" "agent" "$(run_in -- id -un)"
assert_eq "uid is 1000" "1000" "$(run_in -- id -u)"
assert_eq "gid is 1000" "1000" "$(run_in -- id -g)"
# shellcheck disable=SC2016 # expands in the container
assert_eq "home is /home/agent" "/home/agent" "$(run_in -- sh -c 'echo $HOME')"
assert_eq "agent has no extra groups (no adm, sudo)" "agent" "$(run_in -- id -Gn)"
assert_eq "home is owned by agent" "agent:agent" "$(run_in -- stat -c %U:%G /home/agent)"
assert_eq "no ubuntu user" "rc=2" "$(run_in -- sh -c 'getent passwd ubuntu; echo rc=$?')"
# shellcheck disable=SC2016 # expands in the container
assert_eq "LANG is C.UTF-8" "C.UTF-8" "$(run_in -- sh -c 'echo $LANG')"
assert_eq "workdir is /workspace" "/workspace" "$(run_in -- pwd)"
assert_contains "tini is PID 1" "tini" "$(run_in -- cat /proc/1/cmdline | tr '\0' ' ')"
assert_contains "build RUN steps used bash with errexit and pipefail" "errexit pipefail" \
	"$(run_in -- cat /usr/local/share/agentainer/build-shell.txt)"
assert_contains "apt used the snapshot" "snapshot.ubuntu.com" "$(run_in -- cat /usr/local/share/agentainer/apt-policy.txt)"
assert_eq "every installed apt package is from the snapshot" "END" \
	"$(run_in -- sh -c 'cat /usr/local/share/agentainer/apt-unpinned.txt && echo END')"
assert_eq "no snapshot pin left in sources" "rc=1" "$(run_in -- sh -c 'grep -rl "^Snapshot:" /etc/apt; echo rc=$?')"
assert_contains "sources use archive.ubuntu.com" "archive.ubuntu.com" "$(run_in -- cat /etc/apt/sources.list.d/ubuntu.sources)"
assert_eq "sources do not use ports.ubuntu.com" "rc=1" "$(run_in -- sh -c 'grep -rl ports.ubuntu.com /etc/apt; echo rc=$?')"

finish
