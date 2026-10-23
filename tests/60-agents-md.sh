#!/bin/sh
# shellcheck disable=SC2086 # H holds "-v vol:/home/agent" on purpose
# shellcheck disable=SC2016 # single-quoted scripts expand in the container
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"
VOL="agentainer-test-home-$$"
"$RUNTIME" volume create "$VOL" >/dev/null
trap '"$RUNTIME" volume rm -f "$VOL" >/dev/null; rm -rf "${OLD:-}"' EXIT
# dash skips the EXIT trap on a signal; exiting from the signal trap runs it.
trap 'exit 130' INT TERM
H="-v $VOL:/home/agent"

for t in .codex/AGENTS.md .gemini/AGENTS.md .config/opencode/AGENTS.md; do
	assert_eq "$t links to the canonical file" "/home/agent/.agentainer/AGENTS.md" \
		"$(run_in $H -- agentainer-entrypoint readlink "/home/agent/$t")"
done
assert_contains "Claude imports it" "@~/.agentainer/AGENTS.md" "$(run_in $H -- agentainer-entrypoint cat /home/agent/.claude/CLAUDE.md)"
assert_contains "Claude settings enable both instruction files" "claude-md-and-agents-md" "$(run_in $H -- agentainer-entrypoint cat /home/agent/.claude/settings.json)"
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
# and keeps the approval prompts.
assert_contains "Codex filesystem sandbox is off" '"filesystem sandbox": "unrestricted"' "$doctor"
assert_contains "Codex still asks for approval" '"approval policy": "OnRequest"' "$doctor"
prompt=$(run_in $H --network none -- sh -c 'cd /tmp && codex debug prompt-input hi 2>/dev/null')
assert_contains "Codex reads the symlinked AGENTS.md" "Agentainer environment" "$prompt"
assert_contains "Codex receives the image-owned unslop skill reference" "/usr/local/share/agentainer/skills/unslop/SKILL.md" "$prompt"
assert_eq "skill and license match their pins" "UNSLOP_VERIFIED" \
	"$(run_in $H --network none -- sh -ec '
. /usr/local/share/agentainer/versions.env
cd /usr/local/share/agentainer/skills/unslop
printf "%s  SKILL.md\n%s  LICENSE\n" "$UNSLOP_SHA256" "$UNSLOP_LICENSE_SHA256" | sha256sum -c >/dev/null
test "$(stat -c "%U %a" SKILL.md)" = "root 644"
test "$(stat -c "%U %a" LICENSE)" = "root 644"
echo UNSLOP_VERIFIED')"
# A fresh home: no volume, so every first-start step runs.
assert_absent "a fresh start prints no warnings" "$(run_in -- echo STARTED 2>&1)" STARTED warning changed
assert_contains "default AGENTS.md describes the container" "/workspace" "$(run_in $H -- agentainer-entrypoint cat /home/agent/.agentainer/AGENTS.md)"

# A user's own global file is kept, with a warning.
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

# Independent default-upgrade checks use a fresh home without the conflict fixtures.
"$RUNTIME" volume rm -f "$VOL" >/dev/null
"$RUNTIME" volume create "$VOL" >/dev/null

# An unedited file (it matches an earlier image default) follows a new default, with one
# line, when the image is a release. A hash-only line counts as an unknown, older version.
REL="-e AGENTAINER_IMAGE_VERSION=0.1.0"
run_in $H -- agentainer-entrypoint sh -c 'echo "# old default" > ~/.agentainer/AGENTS.md; chmod 600 ~/.agentainer/AGENTS.md; sha256sum ~/.agentainer/AGENTS.md | cut -d" " -f1 > ~/.agentainer/agents-default.sha256' >/dev/null
out=$(run_in $H -e AGENTAINER_IMAGE_VERSION=dev -- agentainer-entrypoint echo STARTED 2>&1)
assert_absent "dev build: unedited file is not replaced" "$out" STARTED "replaced it"
assert_contains "dev build: diff notice instead" "agentainer-agents diff" "$out"
assert_eq "dev build: file kept" "# old default" "$(run_in $H -- agentainer-entrypoint cat /home/agent/.agentainer/AGENTS.md)"
out=$(run_in $H $REL -- agentainer-entrypoint true 2>&1)
assert_contains "unedited file: notice" "replaced it with the new default" "$out"
assert_absent "unedited file: no diff notice" "$out" "replaced it" "agentainer-agents diff"
assert_eq "unedited file: replaced with the new default" "same" \
	"$(run_in $H -- agentainer-entrypoint sh -c 'cmp -s ~/.agentainer/AGENTS.md /etc/agentainer/AGENTS.md && echo same')"
assert_eq "unedited file: owner and mode kept" "agent 600" \
	"$(run_in $H -- agentainer-entrypoint stat -c '%U %a' /home/agent/.agentainer/AGENTS.md)"

# A symlinked AGENTS.md (for example from a dotfiles manager) is never replaced, even
# when its target matches an earlier default.
run_in $H -- agentainer-entrypoint sh -c 'echo "# old default 2" > ~/dotfiles-agents.md; ln -sf ~/dotfiles-agents.md ~/.agentainer/AGENTS.md; sha256sum ~/dotfiles-agents.md | cut -d" " -f1 > ~/.agentainer/agents-default.sha256' >/dev/null
run_in $H $REL -- agentainer-entrypoint true >/dev/null 2>&1
assert_eq "symlinked file: link and target kept" "link # old default 2" \
	"$(run_in $H -- agentainer-entrypoint sh -c 'test -L ~/.agentainer/AGENTS.md && printf "link "; cat ~/dotfiles-agents.md')"
run_in $H -- agentainer-entrypoint sh -c 'rm ~/.agentainer/AGENTS.md ~/dotfiles-agents.md; cp /etc/agentainer/AGENTS.md ~/.agentainer/AGENTS.md' >/dev/null

# An edited file is never touched: a changed default prints one notice and diff shows it.
run_in $H -- agentainer-entrypoint sh -c 'echo "# mine" >> ~/.agentainer/AGENTS.md; echo stale > ~/.agentainer/agents-default.sha256' >/dev/null
assert_contains "notice on changed default" "agentainer-agents diff" "$(run_in $H -- agentainer-entrypoint true 2>&1)"
assert_contains "edited file is kept" "# mine" "$(run_in $H -- agentainer-entrypoint cat /home/agent/.agentainer/AGENTS.md)"
assert_absent "no notice the second time" "$(run_in $H -- agentainer-entrypoint echo STARTED 2>&1)" STARTED "agentainer-agents diff"
# Two images on one home: a default this home has seen before prints nothing, so the
# notice does not flip back and forth. Here the current default is not the last one seen.
run_in $H -- agentainer-entrypoint sh -c 'h=$(sha256sum /etc/agentainer/AGENTS.md | cut -d" " -f1); printf "%s\n" "$h" other > ~/.agentainer/agents-default.sha256' >/dev/null
assert_absent "no notice for a default seen before" "$(run_in $H -- agentainer-entrypoint echo STARTED 2>&1)" STARTED "agentainer-agents diff" "replaced it"
run_in $H -- agentainer-entrypoint sh -c 'echo "# edited" >> ~/.agentainer/AGENTS.md' >/dev/null
assert_contains "diff shows the user's edit" "# edited" "$(run_in $H -- agentainer-entrypoint agentainer-agents diff)"
assert_eq "diff exits 0 when files differ" "rc=0" "$(run_in $H -- agentainer-entrypoint sh -c 'agentainer-agents diff >/dev/null; echo rc=$?')"

# Two release images on one home. The older image's default is mounted over the image's
# own copy. Starting the older image never rolls the file back, and the newer image's
# default stays in place: B, A, B ends with B's default.
"$RUNTIME" volume rm -f "$VOL" >/dev/null
"$RUNTIME" volume create "$VOL" >/dev/null
OLD=$(mktemp -d)
printf '# older default\n' >"$OLD/AGENTS.md"
chmod -R a+rX "$OLD"
A="-v $OLD/AGENTS.md:/etc/agentainer/AGENTS.md:ro -e AGENTAINER_IMAGE_VERSION=0.1.0"
B="-e AGENTAINER_IMAGE_VERSION=0.2.0"
is_default='cmp -s ~/.agentainer/AGENTS.md /etc/agentainer/AGENTS.md && echo same'
run_in $H $B -- agentainer-entrypoint true >/dev/null 2>&1
out=$(run_in $H $A -- agentainer-entrypoint echo STARTED 2>&1)
assert_absent "older image: does not replace the newer default" "$out" STARTED "replaced it"
assert_contains "older image: prints the diff notice for a default not seen before" "agentainer-agents diff" "$out"
assert_absent "older image: no notice the second time" "$(run_in $H $A -- agentainer-entrypoint echo STARTED 2>&1)" STARTED "agentainer-agents diff" "replaced it"
assert_absent "B, A, B: newer image starts quietly" "$(run_in $H $B -- agentainer-entrypoint echo STARTED 2>&1)" STARTED "agentainer-agents diff" "replaced it"
assert_eq "B, A, B: the newer default is kept" "same" "$(run_in $H $B -- agentainer-entrypoint sh -c "$is_default")"
# A, B: a newer release replaces an older release's unedited default.
"$RUNTIME" volume rm -f "$VOL" >/dev/null
"$RUNTIME" volume create "$VOL" >/dev/null
run_in $H $A -- agentainer-entrypoint true >/dev/null 2>&1
assert_contains "A, B: newer release replaces the older default" "replaced it with the new default" \
	"$(run_in $H $B -- agentainer-entrypoint true 2>&1)"
assert_eq "A, B: file is the newer default" "same" "$(run_in $H $B -- agentainer-entrypoint sh -c "$is_default")"
assert_contains "the hash file records the image version" "0.2.0" \
	"$(run_in $H -- agentainer-entrypoint cat /home/agent/.agentainer/agents-default.sha256)"
# A patch release is newer than the prior patch.
run_in $H -v "$OLD/AGENTS.md:/etc/agentainer/AGENTS.md:ro" -e AGENTAINER_IMAGE_VERSION=0.2.1 -- agentainer-entrypoint true >/dev/null 2>&1
assert_eq "a patch release is newer than the prior patch" "# older default" \
	"$(run_in $H -- agentainer-entrypoint cat /home/agent/.agentainer/AGENTS.md)"
rm -rf "$OLD"

finish
