#!/bin/bash -p
# Kelos dispatcher. Kelos starts every agent container with /kelos_entrypoint.sh
# and sets KELOS_AGENT_TYPE. This script refuses a Claude pod that carries
# credentials other than CLAUDE_CODE_OAUTH_TOKEN, then runs the Kelos entrypoint
# for the agent type.
#
# Variable and settings-key names come from the Claude Code docs:
#   https://code.claude.com/docs/en/env-vars
#   https://code.claude.com/docs/en/settings
#   https://code.claude.com/docs/en/settings-reference
# Exit codes: 78 for a refused pod, 2 for an unknown or missing agent type.
#
# Order of work: preflight (refuse BASH_ENV, ENV and exported bash functions),
# guard, proxy CA bundle, guard again, then run the entrypoint as a child. The guard also runs a last time
# in /usr/local/lib/kelos/bin/claude, right before the real claude starts, after
# the Kelos entrypoint has written its files. The Kelos entrypoints stay
# unmodified for that.
set -uo pipefail
# shellcheck disable=SC1091 # exists in the image
. /usr/local/lib/kelos/guard.sh
CAT=/usr/bin/cat MKTEMP=/usr/bin/mktemp

# When the pod gives a proxy CA file, build a bundle of the system CAs plus that
# CA. GIT_SSL_CAINFO and SSL_CERT_FILE replace the whole CA list of the tool that
# reads them, so each must point at the combined file. Readers:
#   git (libcurl)   GIT_SSL_CAINFO   combined bundle
#   gh (Go)         SSL_CERT_FILE    combined bundle (also read by OpenSSL tools)
#   Claude Code     NODE_EXTRA_CA_CERTS  the proxy CA alone; Node adds it to its own list
proxy_ca_setup() {
  local ca=${PROXY_CA_FILE:-} dir bundle
  [ -n "$ca" ] || return 0
  [ -r "$ca" ] || refuse "PROXY_CA_FILE $ca is not readable"
  "$GREP" -q 'BEGIN CERTIFICATE' "$ca" || refuse "PROXY_CA_FILE $ca holds no certificate"
  dir=$("$MKTEMP" -d "${TMPDIR:-/tmp}/kelos-ca.XXXXXX") || refuse "cannot create a directory for the CA bundle"
  bundle="$dir/ca-bundle.crt"
  "$CAT" /etc/ssl/certs/ca-certificates.crt "$ca" >"$bundle" || refuse "cannot write $bundle"
  export GIT_SSL_CAINFO="$bundle" SSL_CERT_FILE="$bundle" NODE_EXTRA_CA_CERTS="$ca"
}

# Runs the Kelos entrypoint as a child of this script, so that this script can stop
# everything in the container on SIGTERM or SIGINT. The traps are set before the
# guards run, so a signal during start-up is not lost.
#
# Why: Kelos starts an agent container with the command /kelos_entrypoint.sh, and
# wraps it in "tini -g --" only for its own bundled images (job_builder.go in Kelos
# v0.62.0, isBundledAgentImage). For this image the process that runs as PID 1 is
# therefore this script. The kernel delivers a signal to PID 1 only if it has a
# handler, and the Kelos entrypoints have none, so this script stays resident and
# handles the signals itself. Without that, SIGTERM would do nothing, and the Kelos
# entrypoint and any tool claude started (a long "sleep" from its shell tool, for
# example) would run until the termination grace period ended and SIGKILL came.
# Kubernetes signals the push sidecar only after this container exits, so a slow
# stop leaves it little time. When this image is started through its own ENTRYPOINT
# ("tini -g --"), tini signals only the process group of its child, which misses
# processes that started their own session (setsid); this script covers that too.
#
# On a signal this script sends SIGTERM to every process of this user in the
# container, waits up to 3 s for them to exit, sends SIGKILL to what is left, and
# exits 143 (130 for SIGINT). kill -1 skips PID 1 and the caller. It relies on the
# container having its own PID namespace, which is the Kubernetes default (a pod
# shares one only with shareProcessNamespace: true, which Kelos does not set). It
# treats the namespace as its own only when this script is PID 1, or when tini is
# PID 1 and this script's direct parent. Otherwise the namespace may be shared with
# other containers (their PID 1 may be tini too), and the script signals only its
# own descendants, so it cannot reach other containers' processes.
child=""
sfd=""
own_ns=0
if [ "$$" -eq 1 ]; then
  own_ns=1
elif [ "$PPID" -eq 1 ] && [ "$(/usr/bin/cat /proc/1/comm 2>/dev/null)" = tini ]; then
  own_ns=1
fi

# Prints the pids of descendants of this script, one per line.
# shellcheck disable=SC2329 # used when the PID namespace may be shared
descendants() {
  local pid ppid stat rest cur depth
  for stat in /proc/[0-9]*/stat; do
    pid=${stat#/proc/}
    pid=${pid%/stat}
    [ "$pid" != "$$" ] || continue
    rest=$(/usr/bin/cat "$stat" 2>/dev/null) || continue
    rest=${rest##*) }
    # shellcheck disable=SC2086 # the stat fields split on purpose
    set -- $rest
    ppid=$2
    cur=$ppid
    depth=0
    while [ -n "$cur" ] && [ "$cur" -gt 1 ] && [ "$depth" -lt 64 ]; do
      if [ "$cur" = "$$" ]; then
        echo "$pid"
        break
      fi
      rest=$(/usr/bin/cat "/proc/$cur/stat" 2>/dev/null) || break
      rest=${rest##*) }
      # shellcheck disable=SC2086 # the stat fields split on purpose
      set -- $rest
      cur=$2
      depth=$((depth + 1))
    done
  done
}

# Sends signal $1 (TERM or KILL) to everything that should stop.
# shellcheck disable=SC2329 # called from on_stop
signal_all() {
  local pid
  if [ "$own_ns" -eq 1 ]; then
    kill -s "$1" -- -1 2>/dev/null
  else
    for pid in $(descendants); do
      kill -s "$1" "$pid" 2>/dev/null
    done
  fi
}

# True while a process other than PID 1 and this script is still running (a zombie
# does not count). In a shared namespace only descendants count.
# shellcheck disable=SC2329 # called from on_stop
others_alive() {
  local status pid state uid
  if [ "$own_ns" -eq 0 ]; then
    for pid in $(descendants); do
      state=$(/usr/bin/grep -m1 '^State:' "/proc/$pid/status" 2>/dev/null)
      case "$state" in *Z* | '') ;; *) return 0 ;; esac
    done
    return 1
  fi
  for status in /proc/[0-9]*/status; do
    pid=${status#/proc/}
    pid=${pid%/status}
    [ "$pid" != 1 ] && [ "$pid" != "$$" ] || continue
    uid=$(/usr/bin/grep -m1 '^Uid:' "$status" 2>/dev/null) || continue
    state=$(/usr/bin/grep -m1 '^State:' "$status" 2>/dev/null) || continue
    case "$state" in *Z*) continue ;; esac
    case "$uid" in *"	$EUID	"*) return 0 ;; esac
  done
  return 1
}

# shellcheck disable=SC2329 # called through the trap below
on_stop() {
  local i code=$1
  trap '' TERM INT
  signal_all TERM
  for ((i = 0; i < 30; i++)); do
    others_alive || break
    read -r -t 0.1 -u "$sfd" || true
  done
  signal_all KILL
  exit "$code"
}

# Opens the stop timer and sets the traps. The timer is a read with a timeout on a
# private fifo, so waiting needs no external sleep.
setup_stop() {
  local fifo_dir
  fifo_dir=$("$MKTEMP" -d "${TMPDIR:-/tmp}/kelos-stop.XXXXXX") || refuse "cannot create a directory for the stop timer"
  /usr/bin/mkfifo "$fifo_dir/f" || refuse "cannot create the stop timer"
  exec {sfd}<>"$fifo_dir/f"
  /usr/bin/rm -rf "$fifo_dir"
  trap 'on_stop 143' TERM
  trap 'on_stop 130' INT
}

# Starts "$@" as a child and exits with its status. stdin stays the container's, and
# the stop timer's file descriptor is closed in the child.
supervise() {
  local rc
  "$@" <&0 {sfd}>&- &
  child=$!
  wait "$child"
  rc=$?
  exit "$rc"
}

setup_stop
kelos_preflight

case "${KELOS_AGENT_TYPE:-}" in
claude-code)
  claude_guard
  proxy_ca_setup
  claude_guard
  # The Claude entrypoint writes KELOS_AGENTS_MD and ~/.claude.json after this
  # point and then runs "claude". The wrapper directory comes first on PATH, so
  # that call runs the guard once more and then the real binary.
  export PATH="/usr/local/lib/kelos/bin:$PATH"
  supervise /kelos_entrypoint_claude.sh "$@"
  ;;
codex)
  codex_guard
  proxy_ca_setup
  supervise /kelos_entrypoint_codex.sh "$@"
  ;;
*)
  printf 'kelos_entrypoint: KELOS_AGENT_TYPE must be claude-code or codex, got "%s"\n' "${KELOS_AGENT_TYPE:-}" >&2
  exit 2
  ;;
esac
