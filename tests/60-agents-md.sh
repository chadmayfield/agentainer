#!/bin/sh
# shellcheck disable=SC2086 # H holds "-v vol:/home/agent" on purpose
# shellcheck disable=SC2016 # single-quoted scripts expand in the container
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"
VOL="agentainer-test-home-$$"
"$RUNTIME" volume create "$VOL" >/dev/null
trap '"$RUNTIME" volume rm -f "$VOL" >/dev/null' EXIT
H="-v $VOL:/home/agent"

for t in .codex/AGENTS.md .gemini/AGENTS.md .config/opencode/AGENTS.md; do
	assert_eq "$t links to the canonical file" "/home/agent/.agentainer/AGENTS.md" \
		"$(run_in $H -- agentainer-entrypoint readlink "/home/agent/$t")"
done
assert_contains "Claude imports it" "@~/.agentainer/AGENTS.md" "$(run_in $H -- agentainer-entrypoint cat /home/agent/.claude/CLAUDE.md)"
assert_contains "Claude loads both instruction files" "claude-md-and-agents-md" "$(run_in $H -- agentainer-entrypoint cat /home/agent/.claude/settings.json)"
assert_contains "Codex stores credentials in a file" 'cli_auth_credentials_store = "file"' "$(run_in $H -- agentainer-entrypoint cat /home/agent/.codex/config.toml)"
assert_contains "OpenCode updates disabled" '"update": "disable"' "$(run_in $H -- agentainer-entrypoint cat /home/agent/.config/opencode/opencode.json)"
# The agents themselves accept the seeded configs (OpenCode drops unknown keys silently).
assert_contains "OpenCode parses the update setting" "disable" "$(run_in $H --network none -- opencode debug config 2>/dev/null)"
doctor=$(run_in $H --network none -- sh -c 'codex --strict-config doctor --json 2>/dev/null')
assert_eq "Codex parses the seeded config strictly" "ok" \
	"$(printf '%s' "$doctor" | python3 -c 'import sys,json; print(json.load(sys.stdin)["checks"]["config.load"]["status"])' 2>&1)"
assert_contains "Codex stores auth in a file" '"auth storage mode": "File"' "$doctor"
# Codex's bubblewrap sandbox cannot start in a container ("bwrap: Can't mount devpts on
# /newroot/dev/pts: Permission denied" under rootless Podman), so the seed turns it off
# and keeps the approval prompts (spec 3.2, D14).
assert_contains "Codex filesystem sandbox is off" '"filesystem sandbox": "unrestricted"' "$doctor"
assert_contains "Codex still asks for approval" '"approval policy": "OnRequest"' "$doctor"
assert_contains "Codex reads the symlinked AGENTS.md" "Agentainer environment" \
	"$(run_in $H --network none -- sh -c 'cd /tmp && codex debug prompt-input hi 2>/dev/null')"
assert_eq "a fresh start prints no warnings" "none" "$(run_in $H -- true 2>&1 | grep -E 'warning|changed' || echo none)"
assert_contains "default AGENTS.md describes the container" "/workspace" "$(run_in $H -- agentainer-entrypoint cat /home/agent/.agentainer/AGENTS.md)"

# Review focus 3: a user's own global file is kept, with a warning.
"$RUNTIME" volume rm -f "$VOL" >/dev/null
"$RUNTIME" volume create "$VOL" >/dev/null
run_in $H --entrypoint sh -- -c 'mkdir -p ~/.codex && echo mine > ~/.codex/AGENTS.md' >/dev/null
out=$(run_in $H -- agentainer-entrypoint cat /home/agent/.codex/AGENTS.md 2>&1)
assert_contains "keeps a real file" "mine" "$out"
assert_contains "warns about the real file" "exists and is not a symlink" "$out"

# A file where an agent's config directory should be warns and does not stop the container.
run_in $H --entrypoint sh -- -c 'rm -rf ~/.config/opencode && echo x > ~/.config/opencode' >/dev/null
out=$(run_in $H -- sh -c 'echo started' 2>&1)
assert_contains "parent path is a file: still starts" "started" "$out"
assert_contains "parent path is a file: warns" "could not link" "$out"
run_in $H --entrypoint sh -- -c 'rm -f ~/.config/opencode' >/dev/null

# A dangling user symlink is kept, with a warning.
run_in $H --entrypoint sh -- -c 'rm -f ~/.gemini/AGENTS.md && ln -s /nonexistent ~/.gemini/AGENTS.md' >/dev/null
out=$(run_in $H -- readlink /home/agent/.gemini/AGENTS.md 2>&1)
assert_contains "keeps a dangling user symlink" "/nonexistent" "$out"
assert_contains "warns about a dangling symlink" "points to a missing file" "$out"

# A changed image default prints one notice and diff shows it.
run_in $H -- agentainer-entrypoint sh -c 'echo stale > ~/.agentainer/agents-default.sha256' >/dev/null
assert_contains "notice on changed default" "agentainer-agents diff" "$(run_in $H -- agentainer-entrypoint true 2>&1)"
assert_eq "no notice the second time" "none" "$(run_in $H -- agentainer-entrypoint true 2>&1 | grep 'agentainer-agents diff' || echo none)"
run_in $H -- agentainer-entrypoint sh -c 'echo "# edited" >> ~/.agentainer/AGENTS.md' >/dev/null
assert_contains "diff shows the user's edit" "# edited" "$(run_in $H -- agentainer-entrypoint agentainer-agents diff)"
assert_eq "diff exits 0 when files differ" "rc=0" "$(run_in $H -- agentainer-entrypoint sh -c 'agentainer-agents diff >/dev/null; echo rc=$?')"

finish
