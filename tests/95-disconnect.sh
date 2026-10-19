#!/bin/sh
# Agents keep running when an attached terminal client is killed, and a new session
# reattaches to them.
# shellcheck disable=SC2016 # single-quoted scripts expand in the container
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"
name="agentainer-disc-$$"
trap '"$RUNTIME" rm -f "$name" >/dev/null 2>&1' EXIT
# dash skips the EXIT trap on a signal; exiting from the signal trap runs it.
trap 'exit 130' INT TERM
run_bg "$name"
x() { "$RUNTIME" exec "$name" "$@"; }
# The entrypoint execs the default command, sleep infinity, after its last step. Agents
# started before then could race the startup steps that write their config.
started() { x pgrep -xf 'sleep infinity'; }
# Every agent window has a live pane whose foreground process is the agent.
agents_up() {
	for _a in claude codex agy opencode; do
		[ "$(x tmux list-panes -t "main:$_a" -F '#{pane_dead}:#{pane_current_command}')" = "0:$_a" ] || return 1
	done
}
# pane_shows SESSION: the session's first pane has printed something.
pane_shows() { x tmux capture-pane -p -t "$1" | grep -q .; }
panes() { x tmux list-panes -a -F '#{window_name}:#{pane_pid}:#{pane_dead}'; }
clients() { x tmux list-clients -t main 2>/dev/null | wc -l | tr -d ' '; }
one_client() { [ "$(clients)" = 1 ]; }
no_client() { [ "$(clients)" = 0 ]; }
# Same panes as before, and there were panes to compare: an empty list equals an empty list.
same_panes() {
	if [ -n "$before" ] && [ "$before" = "$(panes)" ]; then pass "$1"; else fail "$1" "before [$before] now [$(panes)]"; fi
}

assert_eq "tmux config loaded" "allow-passthrough on" "$(x tmux start-server \; show -g allow-passthrough 2>&1)"
assert_eq "tmux config has no invalid lines" "rc=0" "$(x sh -c 'tmux start-server \; source-file /etc/tmux.conf >/dev/null 2>&1; echo rc=$?')"
wait_for 60 started || fail "the entrypoint finished" "no sleep infinity process"
assert_contains "tmux passes truecolor (Tc)" "Tc" "$(x tmux start-server \; show -s terminal-overrides 2>&1)"
assert_eq "Claude truecolor in tmux enabled" "1" "$(x sh -c 'echo "$CLAUDE_CODE_TMUX_TRUECOLOR"')"
x tmux new-session -d -s main
for agent in claude codex agy opencode; do
	x tmux new-window -t main -n "$agent" "$agent"
done
wait_for 60 agents_up || true
before=$(panes)
for agent in claude codex agy opencode; do
	assert_eq "$agent is running in its window" "0:$agent" \
		"$(x tmux list-panes -t "main:$agent" -F '#{pane_dead}:#{pane_current_command}' 2>&1)"
done

# Attach a client with a TTY, as a terminal would ("script" from util-linux provides
# the TTY; tmux needs TERM; "sleep infinity |" keeps stdin open without sending keys),
# then kill it with SIGHUP, as a dropped connection does.
"$RUNTIME" exec -d -e TERM=xterm-256color "$name" sh -c 'sleep infinity | script -qfc "tmux attach -t main" /dev/null >/dev/null 2>&1' >/dev/null
if wait_for 15 one_client; then
	pass "a client is attached"
	x pkill -HUP -f "tmux attach -t main"
	if wait_for 15 no_client; then pass "the client is gone"; else fail "the client is gone" "clients: $(clients)"; fi
else
	fail "a client is attached" "clients: $(clients)"
	fail "the client is gone" "no client was attached"
fi
same_panes "every agent pane survived with the same PID"

# An interactive exec session from the host, killed from the host.
# "script" gives the host-side exec a TTY (BSD syntax on macOS, util-linux on Linux). Its
# stdin stays open and idle: end-of-input would reach the active agent as Ctrl-D, which
# a dropped connection never sends.
if script --version >/dev/null 2>&1; then
	sleep 60 | script -qfc "$RUNTIME exec -it $name tmux new-session -A -s main" /dev/null >/dev/null 2>&1 &
else
	sleep 60 | script -q /dev/null "$RUNTIME" exec -it "$name" tmux new-session -A -s main >/dev/null 2>&1 &
fi
host_session=$!
if wait_for 15 one_client; then pass "the host-side session attached"; else fail "the host-side session attached" "clients: $(clients)"; fi
kill -9 "$host_session" 2>/dev/null
pkill -9 -f "exec -it $name tmux" 2>/dev/null
wait_for 15 no_client || true
same_panes "agents survive a killed host-side exec session"

# Codex must not copy its package into home or leave a daemon behind.
assert_eq "codex left no package copy in home" "none" "$(x sh -c 'ls -d ~/.codex/packages 2>/dev/null || echo none')"
assert_eq "no codex app-server daemon" "none" "$(x sh -c 'pgrep -f "[c]odex app-server" || echo none')"

# Reattach the way users do, from a new exec session. A hook on session main records the
# attach; "script -e" returns tmux's exit status. A failed or misdirected attach leaves no
# marker, and creating a new session instead changes the session list.
sid=$(x tmux display -p -t main '#{session_id}')
x tmux set-hook -t main client-attached 'run-shell "touch /tmp/reattached"'
out=$(x sh -c 'TERM=xterm-256color script -eqfc "tmux new-session -A -s main \; detach" /dev/null 2>&1; echo "rc=$?"')
assert_contains "new-session -A exits 0" "rc=0" "$out"
assert_contains "new-session -A attached to main" "[detached (from session main)]" "$out"
if wait_for 10 x test -e /tmp/reattached; then pass "the attach hook ran on main"; else fail "the attach hook ran on main" "no /tmp/reattached"; fi
x tmux set-hook -u -t main client-attached
assert_eq "reattaching kept the one session" "$sid" "$(x tmux list-sessions -F '#{session_id}')"
same_panes "reattaching keeps every agent process"
x tmux new-session -d -s l 'echo $LANG; sleep 30'
wait_for 10 pane_shows l || true
assert_eq "LANG is UTF-8 inside tmux" "C.UTF-8" "$(x tmux capture-pane -p -t l | head -1)"
x tmux new-session -d -s u 'printf "é\n"; sleep 30'
wait_for 10 pane_shows u || true
assert_contains "UTF-8 passes through tmux" "é" "$(x tmux capture-pane -p -t u)"

finish
