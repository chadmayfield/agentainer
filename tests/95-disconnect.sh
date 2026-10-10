#!/bin/sh
# Spec test 6 and success criterion 4, locally: agents keep running when an attached
# terminal client is killed, and a new session reattaches to them.
# shellcheck disable=SC2016 # single-quoted scripts expand in the container
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"
name="agentainer-disc-$$"
run_bg "$name"
trap '"$RUNTIME" rm -f "$name" >/dev/null 2>&1' EXIT INT TERM
sleep 2
x() { "$RUNTIME" exec "$name" "$@"; }
panes() { x tmux list-panes -a -F '#{window_name}:#{pane_pid}:#{pane_dead}'; }

assert_eq "tmux config loaded" "allow-passthrough on" "$(x tmux start-server \; show -g allow-passthrough 2>&1)"
assert_eq "tmux config has no invalid lines" "rc=0" "$(x sh -c 'tmux start-server \; source-file /etc/tmux.conf >/dev/null 2>&1; echo rc=$?')"
assert_contains "tmux passes truecolor (Tc)" "Tc" "$(x tmux start-server \; show -s terminal-overrides 2>&1)"
assert_eq "Claude truecolor in tmux enabled" "1" "$(x sh -c 'echo "$CLAUDE_CODE_TMUX_TRUECOLOR"')"
x tmux new-session -d -s main
for agent in claude codex agy opencode; do
	x tmux new-window -t main -n "$agent" "$agent"
done
sleep 8
before=$(panes)
for agent in claude codex agy opencode; do
	assert_contains "$agent is running in its window" "$agent:" "$before"
done

# Attach a client with a TTY, as a terminal would ("script" from util-linux provides
# the TTY; tmux needs TERM; "sleep infinity |" keeps stdin open without sending keys),
# then kill it with SIGHUP, as a dropped connection does.
"$RUNTIME" exec -d -e TERM=xterm-256color "$name" sh -c 'sleep infinity | script -qfc "tmux attach -t main" /dev/null >/dev/null 2>&1' >/dev/null
sleep 2
assert_eq "a client is attached" "1" "$(x tmux list-clients -t main | wc -l | tr -d ' ')"
x pkill -HUP -f "tmux attach -t main"
sleep 2
assert_eq "the client is gone" "0" "$(x tmux list-clients -t main | wc -l | tr -d ' ')"
assert_eq "every agent pane survived with the same PID" "$before" "$(panes)"

# Spec test 6 literally: an interactive exec session from the host, killed from the host.
# "script" gives the host-side exec a TTY (BSD syntax on macOS, util-linux on Linux). Its
# stdin stays open and idle: end-of-input would reach the active agent as Ctrl-D, which
# a dropped connection never sends.
if script --version >/dev/null 2>&1; then
	sleep 60 | script -qfc "$RUNTIME exec -it $name tmux new-session -A -s main" /dev/null >/dev/null 2>&1 &
else
	sleep 60 | script -q /dev/null "$RUNTIME" exec -it "$name" tmux new-session -A -s main >/dev/null 2>&1 &
fi
host_session=$!
sleep 3
kill -9 "$host_session" 2>/dev/null
pkill -9 -f "exec -it $name tmux" 2>/dev/null
sleep 2
assert_eq "agents survive a killed host-side exec session" "$before" "$(panes)"

# Codex must not copy its package into home or leave a daemon behind (spec 3.2, 5).
assert_eq "codex left no package copy in home" "none" "$(x sh -c 'ls -d ~/.codex/packages 2>/dev/null || echo none')"
assert_eq "no codex app-server daemon" "none" "$(x sh -c 'pgrep -f "[c]odex app-server" || echo none')"

# Reattach the way users do, from a new exec session.
assert_contains "new-session -A reattaches" "opencode" \
	"$(x sh -c 'script -qfc "tmux new-session -A -s main \; detach" /dev/null >/dev/null 2>&1; tmux list-windows -t main -F "#{window_name}"')"
assert_contains "UTF-8 passes through tmux" "é" \
	"$(x sh -c 'tmux new-session -d -s u "printf \"é\\n\"; sleep 5"; sleep 1; tmux capture-pane -p -t u')"

finish
