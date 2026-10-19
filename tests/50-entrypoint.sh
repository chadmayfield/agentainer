#!/bin/sh
# shellcheck disable=SC2086 # H holds "-v vol:/home/agent" on purpose
# shellcheck disable=SC2016 # single-quoted scripts expand in the container
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"
VOL="agentainer-test-home-$$"
"$RUNTIME" volume create "$VOL" >/dev/null
name="agentainer-test-$$"
trap '"$RUNTIME" rm -f "$name" >/dev/null 2>&1; "$RUNTIME" volume rm -f "$VOL" >/dev/null' EXIT
# dash skips the EXIT trap on a signal; exiting from the signal trap runs it.
trap 'exit 130' INT TERM
H="-v $VOL:/home/agent"

assert_eq "entrypoint runs the command" "hello" "$(run_in $H -- agentainer-entrypoint echo hello)"
assert_eq "tools-active is ephemeral by default" "/var/lib/agentainer/tools" "$(run_in $H -- agentainer-entrypoint readlink /var/lib/agentainer/active)"
assert_eq "image-version stamp written" "yes" "$(run_in $H -- agentainer-entrypoint sh -c 'test -s ~/.agentainer/image-version && echo yes')"
assert_eq "shell dotfiles seeded" "yes" "$(run_in $H -- agentainer-entrypoint sh -c 'test -f ~/.bashrc && test -f ~/.profile && echo yes')"

# Review focus 1: user edits survive a restart.
run_in $H -- agentainer-entrypoint sh -c 'echo "# mine" > ~/.agentainer/AGENTS.md' >/dev/null
assert_eq "keeps edited files" "# mine" "$(run_in $H -- agentainer-entrypoint cat /home/agent/.agentainer/AGENTS.md)"

# Tools install from local fixtures (tests/fixtures/make-tools.sh), with no network.
repo=$(cd "$(dirname "$0")/.." && pwd)
FX="-v $repo/tests/fixtures:/fixtures:ro --network none"
npm_fixture='fx=$(bash /fixtures/make-tools.sh) && npm install -g --offline --no-fund --no-audit "$fx/fixture.tgz" >/dev/null 2>&1'

# Tools land in the active root from an exec session, then vanish in ephemeral mode.
run_bg "$name" -v "$VOL:/home/agent" $FX
wait_for 30 "$RUNTIME" exec "$name" test -L /var/lib/agentainer/active || fail "entrypoint linked the tools root"
assert_eq "npm -g installs from an exec session" "rc=0" "$("$RUNTIME" exec "$name" sh -c "$npm_fixture; echo rc=\$?")"
assert_contains "npm -g lands in tools-active" "/var/lib/agentainer/tools/npm" "$("$RUNTIME" exec "$name" sh -c 'readlink -f "$(command -v fixture-npm)"')"
"$RUNTIME" rm -f "$name" >/dev/null
assert_absent "ephemeral tools gone after restart" "$(run_in $H -- agentainer-entrypoint sh -c 'command -v fixture-npm; echo END')" END fixture-npm

# Persist mode keeps them.
# npx and npm -g need <prefix>/lib before anything is installed (MCP servers start with npx).
assert_eq "npm global prefix is usable on a fresh start" "rc=0" \
	"$(run_in --network none -- agentainer-entrypoint sh -c 'npm ls -g --depth=0 >/dev/null 2>&1; echo rc=$?')"
assert_eq "npm global prefix is usable in persist mode" "rc=0" \
	"$(run_in --network none -e AGENTAINER_TOOLS=persist -- agentainer-entrypoint sh -c 'npm ls -g --depth=0 >/dev/null 2>&1; echo rc=$?')"
assert_eq "npm -g installs in persist mode" "rc=0" "$(run_in $H $FX -e AGENTAINER_TOOLS=persist -- agentainer-entrypoint sh -c "$npm_fixture; echo rc=\$?")"
assert_contains "persist keeps tools" "/home/agent/.agentainer/tools" "$(run_in $H -e AGENTAINER_TOOLS=persist -- agentainer-entrypoint sh -c 'readlink -f "$(command -v fixture-npm)"')"
assert_contains "tools status shows persist" "persist" "$(run_in $H -e AGENTAINER_TOOLS=persist -- agentainer-entrypoint agentainer-tools status)"

# Spec test 4: uv tool and go install land in the active root too.
assert_contains "uv tool lands in tools-active" "/home/agent/.agentainer/tools" "$(run_in $H $FX -e AGENTAINER_TOOLS=persist -- agentainer-entrypoint sh -c 'fx=$(bash /fixtures/make-tools.sh) && uv tool install -q --offline "$fx/fixture_uv-1.0-py3-none-any.whl" >/dev/null 2>&1 && readlink -f "$(command -v fixture-uv)"')"
assert_contains "go install lands in tools-active" "/home/agent/.agentainer/tools" "$(run_in $H $FX -e AGENTAINER_TOOLS=persist -- agentainer-entrypoint sh -c 'fx=$(bash /fixtures/make-tools.sh) && cd "$fx/gomod" && GOFLAGS=-mod=mod go install . >/dev/null 2>&1 && readlink -f "$(command -v fixture)"')"

# Version stamp warning after an image change.
run_in $H -- agentainer-entrypoint sh -c 'echo old > ~/.agentainer/tools-image-version' >/dev/null
assert_contains "warns on image change with persisted tools" "image changed" "$(run_in $H -e AGENTAINER_TOOLS=persist -- agentainer-entrypoint true 2>&1)"
run_in $H -- agentainer-entrypoint agentainer-tools reset >/dev/null
assert_contains "reset renames, never deletes" "tools." "$(run_in $H -- agentainer-entrypoint ls /home/agent/.agentainer)"
assert_eq "npm works right after reset, without a restart" "rc=0" \
	"$(run_in --network none -e AGENTAINER_TOOLS=persist -- agentainer-entrypoint sh -c 'agentainer-tools reset >/dev/null; npm ls -g --depth=0 >/dev/null 2>&1; echo rc=$?')"
assert_eq "reset leaves an empty tools dir" "yes" "$(run_in $H -- agentainer-entrypoint sh -c 'test -d ~/.agentainer/tools/bin && echo yes')"

# A bad AGENTAINER_TOOLS value falls back to ephemeral with a warning.
assert_contains "bad AGENTAINER_TOOLS warns" "not ephemeral or persist" "$(run_in $H -e AGENTAINER_TOOLS=bogus -- agentainer-entrypoint true 2>&1)"

# ConfigMap seed is used only when the file is missing.
"$RUNTIME" volume rm -f "$VOL" >/dev/null
"$RUNTIME" volume create "$VOL" >/dev/null
SEED=$(mktemp -d)
echo "# from seed" >"$SEED/AGENTS.md"
chmod -R a+rX "$SEED"
assert_eq "seed ConfigMap used when missing" "# from seed" "$(run_in $H -v "$SEED:/etc/agentainer/seed:ro" -- agentainer-entrypoint cat /home/agent/.agentainer/AGENTS.md)"
rm -rf "$SEED"

# A failing required step stops the container.
assert_contains "required step failure stops startup" "required step" "$(run_in $H -e HOME=/nonexistent/x --entrypoint /usr/local/bin/agentainer-entrypoint -- true 2>&1)"
assert_contains "unwritable home names the path and uid" "/nonexistent/x is not writable by uid 1000" \
	"$(run_in $H -e HOME=/nonexistent/x --entrypoint /usr/local/bin/agentainer-entrypoint -- true 2>&1)"

# Each container keeps its own tools mode, even on a shared home volume.
"$RUNTIME" volume rm -f "$VOL" >/dev/null
"$RUNTIME" volume create "$VOL" >/dev/null
run_bg "$name" -v "$VOL:/home/agent" -e AGENTAINER_TOOLS=persist
sleep 1
run_in $H -- true >/dev/null 2>&1
assert_eq "persist container stays persist after an ephemeral start on the same volume" "/home/agent/.agentainer/tools" \
	"$("$RUNTIME" exec "$name" readlink /var/lib/agentainer/active)"
"$RUNTIME" rm -f "$name" >/dev/null

# The stale-tools warning repeats on every start until reset.
run_in $H -e AGENTAINER_TOOLS=persist -- sh -c 'mkdir -p ~/.agentainer/tools/bin && touch ~/.agentainer/tools/bin/foo && echo old > ~/.agentainer/tools-image-version' >/dev/null 2>&1
run_in $H -e AGENTAINER_TOOLS=persist -- true >/dev/null 2>&1
assert_contains "warning repeats on the next start" "image changed" "$(run_in $H -e AGENTAINER_TOOLS=persist -- true 2>&1)"
run_in $H -- agentainer-tools reset >/dev/null 2>&1
assert_absent "no warning after reset" "$(run_in $H -e AGENTAINER_TOOLS=persist -- echo STARTED 2>&1)" STARTED "image changed"
run_in $H -- sh -c 'agentainer-tools reset; mkdir -p ~/.agentainer/tools/bin; agentainer-tools reset' >/dev/null 2>&1
assert_eq "two resets make two separate backups" "rc=0" \
	"$(run_in $H -- sh -c 'n=$(ls -d ~/.agentainer/tools.*.bak | wc -l); [ "$n" -ge 2 ] && ! ls -d ~/.agentainer/tools.*.bak/tools >/dev/null 2>&1; echo rc=$?')"

# A user file in the way of a seed path warns and does not stop the container.
"$RUNTIME" volume rm -f "$VOL" >/dev/null
"$RUNTIME" volume create "$VOL" >/dev/null
run_in $H --entrypoint sh -- -c 'echo mine > ~/.claude' >/dev/null
out=$(run_in $H -- sh -c 'echo started' 2>&1)
assert_contains "blocked seed path still starts" "started" "$out"
assert_contains "blocked seed path warns" "could not seed" "$out"

# Login shells keep image directories ahead of ~/.local/bin (spec 10).
# Both directories present, and /usr/local/bin first (compared by position in PATH).
assert_eq "bash -l keeps /usr/local/bin before ~/.local/bin" "rc=0" \
	"$(run_in $H -- bash -l -c 'mkdir -p ~/.local/bin; p=$(bash -l -c "echo \$PATH")
		a=$(echo "$p" | tr : "\n" | grep -nx /usr/local/bin | head -1 | cut -d: -f1)
		b=$(echo "$p" | tr : "\n" | grep -nx /home/agent/.local/bin | head -1 | cut -d: -f1)
		if [ -n "$a" ] && [ -n "$b" ] && [ "$a" -lt "$b" ]; then echo rc=0; else echo "rc=1 PATH=$p"; fi' 2>/dev/null)"

# Optional steps report a failure and the container still starts.
assert_contains "a failing opencode setup step warns" "70-opencode.sh failed" \
	"$(run_in --entrypoint sh -- -c 'mkdir -p /tmp/f && printf "#!/bin/sh\nexit 1\n" >/tmp/f/opencode && chmod +x /tmp/f/opencode && PATH=/tmp/f:$PATH agentainer-entrypoint echo started 2>&1')"

finish
