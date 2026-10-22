#!/bin/sh
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"

assert_eq "user is agent" "agent" "$(run_in -- id -un)"
assert_eq "uid is 1000" "1000" "$(run_in -- id -u)"
assert_eq "gid is 1000" "1000" "$(run_in -- id -g)"
# shellcheck disable=SC2016 # expands in the container
assert_eq "home is /home/agent" "/home/agent" "$(run_in -- sh -c 'echo $HOME')"
assert_eq "agent belongs only to the agent group" "agent" "$(run_in -- id -Gn)"
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
# Root reads every directory, so find exits 0 and prints END only after a full walk; an
# error message lands in the output and fails the check.
assert_eq "no macOS .DS_Store files in the image" "END" \
	"$(run_in --user root --entrypoint sh -- -c 'find / -xdev -name .DS_Store 2>&1 && echo END')"
# Build steps that run a tool as root can leave state in /root, which would ship in the image.
# /root holds only the base image's shell startup files.
assert_eq "no build leftovers in /root" "/root/.bashrc /root/.profile" \
	"$(run_in --user root --entrypoint find -- /root -mindepth 1 2>&1 | sort | paste -sd ' ' -)"
# The build sets fixed modes on everything from rootfs/, whatever the build host's umask.
assert_eq "rootfs paths have fixed modes" "755 /etc
755 /usr/local/bin
755 /usr/local/lib/agentainer/entrypoint.d
644 /etc/agentainer/home/.profile
644 /usr/local/lib/agentainer/entrypoint.d/10-dirs.sh
755 /usr/local/bin/agentainer-entrypoint" "$(run_in --entrypoint stat -- -c '%a %n' /etc /usr/local/bin \
	/usr/local/lib/agentainer/entrypoint.d /etc/agentainer/home/.profile \
	/usr/local/lib/agentainer/entrypoint.d/10-dirs.sh /usr/local/bin/agentainer-entrypoint)"

# Not in the image: the base image's unused Pebble service manager and ImageMagick, which
# add scanner findings.
assert_eq "no pebble from the base image" "none" "$(run_in -- sh -c 'ls /usr/bin/pebble /var/lib/pebble 2>/dev/null || echo none')"
assert_eq "no ImageMagick" "none" "$(run_in -- sh -c 'command -v magick convert || dpkg -l "imagemagick*" 2>/dev/null | grep ^ii || echo none')"

finish
