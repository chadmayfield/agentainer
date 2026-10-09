#!/bin/sh
# shellcheck disable=SC2086 # H holds "-v vol:/home/agent" on purpose
# shellcheck disable=SC2016 # single-quoted scripts expand in the container
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"
VOL="agentbox-test-home-$$"
"$RUNTIME" volume create "$VOL" >/dev/null
name="agentbox-test-$$"
trap '"$RUNTIME" rm -f "$name" >/dev/null 2>&1; "$RUNTIME" volume rm -f "$VOL" >/dev/null' EXIT
H="-v $VOL:/home/agent"

assert_eq "entrypoint runs the command" "hello" "$(run_in $H -- agentbox-entrypoint echo hello)"
assert_eq "tools-active is ephemeral by default" "/var/lib/agentbox/tools" "$(run_in $H -- agentbox-entrypoint readlink /var/lib/agentbox/active)"
assert_eq "image-version stamp written" "yes" "$(run_in $H -- agentbox-entrypoint sh -c 'test -s ~/.agentbox/image-version && echo yes')"
assert_eq "shell dotfiles seeded" "yes" "$(run_in $H -- agentbox-entrypoint sh -c 'test -f ~/.bashrc && test -f ~/.profile && echo yes')"

# Review focus 1: user edits survive a restart.
run_in $H -- agentbox-entrypoint sh -c 'echo "# mine" > ~/.agentbox/AGENTS.md' >/dev/null
assert_eq "keeps edited files" "# mine" "$(run_in $H -- agentbox-entrypoint cat /home/agent/.agentbox/AGENTS.md)"

# Tools land in the active root from an exec session, then vanish in ephemeral mode.
run_bg "$name" -v "$VOL:/home/agent"
"$RUNTIME" exec "$name" npm install -g --no-fund --no-audit cowsay >/dev/null 2>&1
assert_contains "npm -g lands in tools-active" "/var/lib/agentbox/tools/npm" "$("$RUNTIME" exec "$name" sh -c 'readlink -f "$(command -v cowsay)"')"
"$RUNTIME" rm -f "$name" >/dev/null
assert_eq "ephemeral tools gone after restart" "none" "$(run_in $H -- agentbox-entrypoint sh -c 'command -v cowsay || echo none')"

# Persist mode keeps them.
run_in $H -e AGENTBOX_TOOLS=persist -- agentbox-entrypoint npm install -g --no-fund --no-audit cowsay >/dev/null 2>&1
assert_contains "persist keeps tools" "/home/agent/.agentbox/tools" "$(run_in $H -e AGENTBOX_TOOLS=persist -- agentbox-entrypoint sh -c 'readlink -f "$(command -v cowsay)"')"
assert_contains "tools status shows persist" "persist" "$(run_in $H -e AGENTBOX_TOOLS=persist -- agentbox-entrypoint agentbox-tools status)"

# Spec test 4: uv tool and go install land in the active root too.
assert_contains "uv tool lands in tools-active" "/home/agent/.agentbox/tools" "$(run_in $H -e AGENTBOX_TOOLS=persist -- agentbox-entrypoint sh -c 'uv tool install -q ruff >/dev/null 2>&1; readlink -f "$(command -v ruff)"')"
assert_contains "go install lands in tools-active" "/home/agent/.agentbox/tools" "$(run_in $H -e AGENTBOX_TOOLS=persist -- agentbox-entrypoint sh -c 'go install golang.org/x/example/hello@latest >/dev/null 2>&1; readlink -f "$(command -v hello)"')"

# Version stamp warning after an image change.
run_in $H -- agentbox-entrypoint sh -c 'echo old > ~/.agentbox/tools-image-version' >/dev/null
assert_contains "warns on image change with persisted tools" "image changed" "$(run_in $H -e AGENTBOX_TOOLS=persist -- agentbox-entrypoint true 2>&1)"
run_in $H -- agentbox-entrypoint agentbox-tools reset >/dev/null
assert_contains "reset renames, never deletes" "tools." "$(run_in $H -- agentbox-entrypoint ls /home/agent/.agentbox)"
assert_eq "reset leaves an empty tools dir" "yes" "$(run_in $H -- agentbox-entrypoint sh -c 'test -d ~/.agentbox/tools/bin && echo yes')"

# A bad AGENTBOX_TOOLS value falls back to ephemeral with a warning.
assert_contains "bad AGENTBOX_TOOLS warns" "not ephemeral or persist" "$(run_in $H -e AGENTBOX_TOOLS=bogus -- agentbox-entrypoint true 2>&1)"

# ConfigMap seed is used only when the file is missing.
"$RUNTIME" volume rm -f "$VOL" >/dev/null
"$RUNTIME" volume create "$VOL" >/dev/null
SEED=$(mktemp -d)
echo "# from seed" >"$SEED/AGENTS.md"
chmod -R a+rX "$SEED"
assert_eq "seed ConfigMap used when missing" "# from seed" "$(run_in $H -v "$SEED:/etc/agentbox/seed:ro" -- agentbox-entrypoint cat /home/agent/.agentbox/AGENTS.md)"
rm -rf "$SEED"

# A failing required step stops the container.
assert_contains "required step failure stops startup" "required step" "$(run_in $H -e HOME=/nonexistent/x --entrypoint /usr/local/bin/agentbox-entrypoint -- true 2>&1)"
assert_contains "unwritable home names the path and uid" "/nonexistent/x is not writable by uid 1000" \
	"$(run_in $H -e HOME=/nonexistent/x --entrypoint /usr/local/bin/agentbox-entrypoint -- true 2>&1)"

# Each container keeps its own tools mode, even on a shared home volume.
"$RUNTIME" volume rm -f "$VOL" >/dev/null
"$RUNTIME" volume create "$VOL" >/dev/null
run_bg "$name" -v "$VOL:/home/agent" -e AGENTBOX_TOOLS=persist
sleep 1
run_in $H -- true >/dev/null 2>&1
assert_eq "persist container stays persist after an ephemeral start on the same volume" "/home/agent/.agentbox/tools" \
	"$("$RUNTIME" exec "$name" readlink /var/lib/agentbox/active)"
"$RUNTIME" rm -f "$name" >/dev/null

# The stale-tools warning repeats on every start until reset.
run_in $H -e AGENTBOX_TOOLS=persist -- sh -c 'mkdir -p ~/.agentbox/tools/bin && touch ~/.agentbox/tools/bin/foo && echo old > ~/.agentbox/tools-image-version' >/dev/null 2>&1
run_in $H -e AGENTBOX_TOOLS=persist -- true >/dev/null 2>&1
assert_contains "warning repeats on the next start" "image changed" "$(run_in $H -e AGENTBOX_TOOLS=persist -- true 2>&1)"
run_in $H -- agentbox-tools reset >/dev/null 2>&1
assert_eq "no warning after reset" "none" "$(run_in $H -e AGENTBOX_TOOLS=persist -- true 2>&1 | grep 'image changed' || echo none)"
run_in $H -- sh -c 'agentbox-tools reset; mkdir -p ~/.agentbox/tools/bin; agentbox-tools reset' >/dev/null 2>&1
assert_eq "two resets make two separate backups" "rc=0" \
	"$(run_in $H -- sh -c 'n=$(ls -d ~/.agentbox/tools.*.bak | wc -l); [ "$n" -ge 2 ] && ! ls -d ~/.agentbox/tools.*.bak/tools >/dev/null 2>&1; echo rc=$?')"

# A user file in the way of a seed path warns and does not stop the container.
"$RUNTIME" volume rm -f "$VOL" >/dev/null
"$RUNTIME" volume create "$VOL" >/dev/null
run_in $H --entrypoint sh -- -c 'echo mine > ~/.claude' >/dev/null
out=$(run_in $H -- sh -c 'echo started' 2>&1)
assert_contains "blocked seed path still starts" "started" "$out"
assert_contains "blocked seed path warns" "could not seed" "$out"

# Login shells keep image directories ahead of ~/.local/bin (spec 10).
assert_eq "bash -l keeps /usr/local/bin before ~/.local/bin" "rc=0" \
	"$(run_in $H -- bash -l -c 'mkdir -p ~/.local/bin; p=$(bash -l -c "echo \$PATH"); case "$p" in */usr/local/bin*/home/agent/.local/bin* | */usr/local/bin*) ;; *) exit 1 ;; esac; case "$p" in /home/agent/.local/bin:*) exit 1 ;; esac; echo rc=0' 2>/dev/null || echo rc=1)"

finish
