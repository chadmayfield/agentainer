#!/bin/sh
# Tests for the Kelos variant image. Set IMAGE to the image under test.
# Usage: IMAGE=localhost/agentainer-kelos:dev sh tests/kelos/test_image.sh
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/../lib.sh"

# kr runs a command in the image with the image entrypoint cleared, so the command is
# not passed to the dispatcher. No test needs the network.
kr() {
	run_in --network none --entrypoint '' "$@"
}

assert_eq "runs as uid 61100" "61100" "$(kr -- id -u)"
assert_eq "dispatcher is executable" "yes" "$(kr -- sh -c 'test -x /kelos_entrypoint.sh && echo yes')"
assert_eq "kelos-capture is executable" "yes" "$(kr -- sh -c 'test -x /kelos/kelos-capture && echo yes')"
assert_eq "claude entrypoint is executable" "yes" "$(kr -- sh -c 'test -x /kelos_entrypoint_claude.sh && echo yes')"
assert_eq "codex entrypoint is executable" "yes" "$(kr -- sh -c 'test -x /kelos_entrypoint_codex.sh && echo yes')"
assert_contains "claude --version" "(Claude Code)" "$(kr --timeout 120 -- claude --version 2>&1)"
assert_contains "codex --version" "codex-cli" "$(kr -- codex --version 2>&1)"
assert_contains "git --version" "git version" "$(kr -- git --version 2>&1)"
assert_eq "gh on PATH is the Kelos wrapper" "/usr/local/bin/gh" "$(kr -- sh -c 'command -v gh')"
assert_contains "gh wrapper text" "gh wrapper for Kelos agent containers" "$(kr -- head -n 2 /usr/local/bin/gh)"
assert_contains "real gh runs through the wrapper" "gh version" "$(kr -- gh --version 2>&1)"
# shellcheck disable=SC2016 # expands in the container
assert_eq "home .local/bin is writable and on PATH" "ok" \
	"$(kr -- sh -c 'touch ~/.local/bin/t && rm ~/.local/bin/t && case ":$PATH:" in *":$HOME/.local/bin:"*) echo ok ;; esac')"
assert_eq "baked unslop skill" "yes" "$(kr -- sh -c 'test -f /usr/local/share/agentainer/skills/unslop/SKILL.md && echo yes')"

# Guard: each forbidden Claude credential must stop the dispatcher and be named.
for var in ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN CLAUDE_CODE_USE_BEDROCK \
	CLAUDE_CODE_USE_VERTEX CLAUDE_CODE_USE_FOUNDRY CLAUDE_CODE_USE_MANTLE \
	CLAUDE_CODE_USE_ANTHROPIC_AWS AWS_BEARER_TOKEN_BEDROCK ANTHROPIC_BASE_URL; do
	out=$(kr -e KELOS_AGENT_TYPE=claude-code -e KELOS_SESSION_SETUP_ONLY=1 -e "$var=x" -- /kelos_entrypoint.sh 2>&1)
	rc=$?
	if [ "$rc" -ne 0 ]; then pass "guard exits non-zero for $var"; else fail "guard exits non-zero for $var" "exit $rc"; fi
	assert_contains "guard names $var" "$var" "$out"
done

# Guard: a settings file with a credential helper.
for key in apiKeyHelper awsAuthRefresh awsCredentialExport gcpAuthRefresh; do
	# shellcheck disable=SC2016 # expands in the container
	out=$(kr -e KELOS_AGENT_TYPE=claude-code -e KELOS_SESSION_SETUP_ONLY=1 -- sh -c '
		mkdir -p ~/.claude && printf "{\"'"$key"'\": \"/bin/true\"}" > ~/.claude/settings.json
		/kelos_entrypoint.sh' 2>&1)
	rc=$?
	if [ "$rc" -ne 0 ]; then pass "guard exits non-zero for user settings $key"; else fail "guard exits non-zero for user settings $key" "exit $rc"; fi
	assert_contains "guard names $key" "$key" "$out"
done
# shellcheck disable=SC2016 # expands in the container
out=$(kr -e KELOS_AGENT_TYPE=claude-code -e KELOS_SESSION_SETUP_ONLY=1 -- sh -c '
	mkdir -p /tmp/repo/.claude && cd /tmp/repo && git init -q \
	&& printf "{\"apiKeyHelper\": \"x\"}" > .claude/settings.local.json
	/kelos_entrypoint.sh' 2>&1)
rc=$?
if [ "$rc" -ne 0 ]; then pass "guard exits non-zero for project local settings"; else fail "guard exits non-zero for project local settings" "exit $rc"; fi
assert_contains "guard names apiKeyHelper in project local file" "apiKeyHelper" "$out"

# A clean Claude pod gets through the guard.
kr -e KELOS_AGENT_TYPE=claude-code -e KELOS_SESSION_SETUP_ONLY=1 -e CLAUDE_CODE_OAUTH_TOKEN=x -- /kelos_entrypoint.sh >/dev/null 2>&1
assert_eq "clean claude pod passes the guard" "0" "$?"

# Dispatcher refuses a missing or unknown agent type.
kr -- /kelos_entrypoint.sh >/dev/null 2>&1
assert_eq "no KELOS_AGENT_TYPE exits 2" "2" "$?"
kr -e KELOS_AGENT_TYPE=gemini -- /kelos_entrypoint.sh >/dev/null 2>&1
assert_eq "unknown KELOS_AGENT_TYPE exits 2" "2" "$?"

# Codex: auth.json is seeded only when missing, and a valid file for the same
# account is kept. The tokens below are fake. Codex parses id_token as a JWT, so
# fake_jwt has that shape: header {"alg":"none","typ":"JWT"}, payload
# {"email":"a@example.com","https://api.openai.com/auth":{"chatgpt_account_id":"acct-a"}}
# and the signature "sig".
fake_jwt=eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJlbWFpbCI6ImFAZXhhbXBsZS5jb20iLCJodHRwczovL2FwaS5vcGVuYWkuY29tL2F1dGgiOnsiY2hhdGdwdF9hY2NvdW50X2lkIjoiYWNjdC1hIn19.sig
old_auth='{"tokens":{"id_token":"'"$fake_jwt"'","access_token":"at-old","refresh_token":"rt-old","account_id":"acct-a"}}'
# shellcheck disable=SC2016 # expands in the container
assert_eq "codex keeps an existing auth.json" "$old_auth" "$(kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -e 'CODEX_AUTH_JSON={"tokens":{"id_token":"id-new","access_token":"at-new","refresh_token":"rt-new","account_id":"acct-a"}}' -e "OLD_AUTH=$old_auth" -- sh -c '
	mkdir -p ~/.codex && printf "%s" "$OLD_AUTH" > ~/.codex/auth.json
	/kelos_entrypoint.sh
	cat ~/.codex/auth.json' 2>&1)"
# shellcheck disable=SC2016 # expands in the container
assert_eq "codex writes auth.json when missing" '{"new":1}' "$(kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -e 'CODEX_AUTH_JSON={"new":1}' -- sh -c '
	rm -f ~/.codex/auth.json
	/kelos_entrypoint.sh
	cat ~/.codex/auth.json' 2>&1)"

# Guard: a JSON unicode escape must not hide a key (the key below is apiKeyHelper).
# shellcheck disable=SC2016 # expands in the container
out=$(kr -e KELOS_AGENT_TYPE=claude-code -e KELOS_SESSION_SETUP_ONLY=1 -- sh -c '
	mkdir -p ~/.claude && printf "{\"\\u0061piKeyHelper\": \"/bin/true\"}" > ~/.claude/settings.json
	/kelos_entrypoint.sh' 2>&1)
rc=$?
if [ "$rc" -eq 78 ]; then pass "guard refuses an escaped apiKeyHelper"; else fail "guard refuses an escaped apiKeyHelper" "exit $rc"; fi
assert_contains "guard names the decoded key" "apiKeyHelper" "$out"
# shellcheck disable=SC2016 # expands in the container
kr -e KELOS_AGENT_TYPE=claude-code -e KELOS_SESSION_SETUP_ONLY=1 -- sh -c '
	mkdir -p ~/.claude && printf "{\"env\": {\"\\u0041NTHROPIC_API_KEY\": \"x\"}}" > ~/.claude/settings.json
	/kelos_entrypoint.sh' >/dev/null 2>&1
assert_eq "guard refuses an escaped key inside an env block" "78" "$?"
# shellcheck disable=SC2016 # expands in the container
kr -e KELOS_AGENT_TYPE=claude-code -e KELOS_SESSION_SETUP_ONLY=1 -- sh -c '
	mkdir -p ~/.claude && printf "{not json" > ~/.claude/settings.json
	/kelos_entrypoint.sh' >/dev/null 2>&1
assert_eq "guard refuses a settings file that is not JSON" "78" "$?"
# shellcheck disable=SC2016 # expands in the container
kr -e KELOS_AGENT_TYPE=claude-code -e KELOS_SESSION_SETUP_ONLY=1 -- sh -c '
	mkdir -p ~/.claude && printf "{\"permissions\": {\"allow\": []}}" > ~/.claude/settings.json
	/kelos_entrypoint.sh' >/dev/null 2>&1
assert_eq "guard accepts valid settings without forbidden keys" "0" "$?"

# Guard: loader variables are refused, and a loader file cannot add a key.
for var in BASH_ENV ENV; do
	out=$(kr -e KELOS_AGENT_TYPE=claude-code -e KELOS_SESSION_SETUP_ONLY=1 -e "$var=/tmp/loader" -- /kelos_entrypoint.sh 2>&1)
	rc=$?
	if [ "$rc" -eq 78 ]; then pass "guard refuses $var"; else fail "guard refuses $var" "exit $rc"; fi
	assert_contains "guard names $var" "$var" "$out"
done
kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -e BASH_ENV=/tmp/loader -- /kelos_entrypoint.sh >/dev/null 2>&1
assert_eq "BASH_ENV is refused for codex too" "78" "$?"
# KELOS_SETUP_COMMAND runs after the guard, so a Claude pod that has one is refused.
out=$(kr -e KELOS_AGENT_TYPE=claude-code -e KELOS_SESSION_SETUP_ONLY=1 -e 'KELOS_SETUP_COMMAND=["true"]' -- /kelos_entrypoint.sh 2>&1)
rc=$?
if [ "$rc" -eq 78 ]; then pass "guard refuses KELOS_SETUP_COMMAND on a Claude pod"; else fail "guard refuses KELOS_SETUP_COMMAND on a Claude pod" "exit $rc"; fi
assert_contains "guard names KELOS_SETUP_COMMAND" "KELOS_SETUP_COMMAND" "$out"
# Lowercase spelling of a forbidden variable.
kr -e KELOS_AGENT_TYPE=claude-code -e KELOS_SESSION_SETUP_ONLY=1 -e anthropic_api_key=x -- /kelos_entrypoint.sh >/dev/null 2>&1
assert_eq "guard refuses a lowercase anthropic_api_key" "78" "$?"

# Codex: a second start on the same home keeps one setting and the first auth.json.
# No prompt is given, so each start stops right after writing its files.
# shellcheck disable=SC2016 # expands in the container
assert_eq "second codex start leaves one cli_auth_credentials_store line" "1" "$(kr -e KELOS_AGENT_TYPE=codex -e 'CODEX_AUTH_JSON={"new":1}' -- sh -c '
	rm -rf ~/.codex; mkdir -p ~/.codex
	/kelos_entrypoint.sh >/dev/null 2>&1
	/kelos_entrypoint.sh >/dev/null 2>&1
	grep -c "^cli_auth_credentials_store" ~/.codex/config.toml' 2>&1)"
# shellcheck disable=SC2016 # expands in the container
assert_eq "auth.json has mode 600" "600" "$(kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -e 'CODEX_AUTH_JSON={"new":1}' -- sh -c '
	rm -rf ~/.codex; mkdir -p ~/.codex
	/kelos_entrypoint.sh
	stat -c %a ~/.codex/auth.json' 2>&1)"

# Codex: each start removes everything in CODEX_HOME except auth.json, then writes
# config.toml and AGENTS.md. Planted files, a subdirectory and a dotfile must be gone,
# and auth.json must keep its exact bytes and mode.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -e 'CODEX_AUTH_JSON={"tokens":{"id_token":"id-new","access_token":"at-new","refresh_token":"rt-new","account_id":"acct-a"}}' -e 'KELOS_AGENTS_MD=fresh rules' -e "FAKE_JWT=$fake_jwt" -- sh -c '
	h=/home/kelos/.codex
	printf "{\"tokens\":{\"id_token\":\"%s\",\"access_token\":\"a1\",\"refresh_token\":\"r1\",\"account_id\":\"acct-a\"}}\n" "$FAKE_JWT" > $h/auth.json && chmod 600 $h/auth.json
	before=$(sha256sum < $h/auth.json)
	printf "model = \"planted\"\n" > $h/config.toml
	printf "planted rules\n" > $h/EXTRA.md
	mkdir -p $h/sessions/old && printf "planted\n" > $h/sessions/old/rollout.jsonl
	printf "planted\n" > $h/.hidden
	/kelos_entrypoint.sh; echo "rc=$?"
	echo "entries=$(LC_ALL=C ls -A $h | tr "\n" ",")end"
	[ "$(sha256sum < $h/auth.json)" = "$before" ] && echo auth=same || echo auth=changed
	echo "mode=$(stat -c %a $h/auth.json)"
	echo "config=$(cat $h/config.toml)"
	echo "agents=$(cat $h/AGENTS.md)"' 2>&1)
assert_contains "reset: the start succeeds" "rc=0" "$out"
assert_contains "reset: only AGENTS.md, auth.json and config.toml remain" "entries=AGENTS.md,auth.json,config.toml,end" "$out"
assert_contains "reset: auth.json is byte-identical" "auth=same" "$out"
assert_contains "reset: auth.json keeps mode 600" "mode=600" "$out"
assert_contains "reset: config.toml is written fresh" 'config=cli_auth_credentials_store = "file"
' "$out"
assert_contains "reset: AGENTS.md is written fresh" "agents=fresh rules" "$out"
assert_absent "reset: no planted content survives" "$out" "rc=0" "planted" ".hidden" "EXTRA.md" "sessions"

# Symlinks in CODEX_HOME are removed as links and never followed: a link named
# config.toml, a link to a directory, and a link inside a subdirectory.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -e 'CODEX_AUTH_JSON={"new":1}' -- sh -c '
	h=/home/kelos/.codex
	mkdir -p /tmp/out/dir && printf "keep\n" > /tmp/out/target.toml && printf "keep\n" > /tmp/out/dir/inner
	ln -s /tmp/out/target.toml $h/config.toml
	ln -s /tmp/out/dir $h/linkdir
	mkdir $h/sub && ln -s /tmp/out/dir $h/sub/link
	/kelos_entrypoint.sh; echo "rc=$?"
	echo "entries=$(LC_ALL=C ls -A $h | tr "\n" ",")end"
	[ -L $h/config.toml ] && echo config=link || echo config=notlink
	echo "target=$(cat /tmp/out/target.toml)"
	echo "inner=$(cat /tmp/out/dir/inner)"
	echo "outside=$(LC_ALL=C ls -A /tmp/out | tr "\n" ",")end"' 2>&1)
assert_contains "reset with symlinks: the start succeeds" "rc=0" "$out"
assert_contains "reset with symlinks: the links are gone" "entries=auth.json,config.toml,end" "$out"
assert_contains "reset with symlinks: config.toml is a new regular file" "config=notlink" "$out"
assert_contains "reset with symlinks: the file target is untouched" "target=keep" "$out"
assert_contains "reset with symlinks: the directory target is untouched" "inner=keep" "$out"
assert_contains "reset with symlinks: nothing outside was removed" "outside=dir,target.toml,end" "$out"

# An auth.json that is a symlink, or not a regular file, is refused before anything is removed.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -- sh -c '
	h=/home/kelos/.codex
	printf "outside\n" > /tmp/auth-target.json
	ln -s /tmp/auth-target.json $h/auth.json
	printf "x\n" > $h/EXTRA.md
	/kelos_entrypoint.sh; echo "rc=$?"
	echo "target=$(cat /tmp/auth-target.json)"
	echo "entries=$(LC_ALL=C ls -A $h | tr "\n" ",")end"' 2>&1)
assert_contains "auth.json symlink: refused with exit 78" "rc=78" "$out"
assert_contains "auth.json symlink: the refusal names it" "auth.json is a symlink" "$out"
assert_contains "auth.json symlink: the target is untouched" "target=outside" "$out"
assert_contains "auth.json symlink: nothing was removed" "entries=EXTRA.md,auth.json,end" "$out"
# shellcheck disable=SC2016 # expands in the container
out=$(kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -- sh -c '
	mkdir /home/kelos/.codex/auth.json && printf "x\n" > /home/kelos/.codex/EXTRA.md
	/kelos_entrypoint.sh; echo "rc=$?"
	echo "entries=$(LC_ALL=C ls -A /home/kelos/.codex | tr "\n" ",")end"' 2>&1)
assert_contains "auth.json directory: refused with exit 78" "rc=78" "$out"
assert_contains "auth.json directory: the refusal says why" "auth.json is not a regular file" "$out"
assert_contains "auth.json directory: nothing was removed" "entries=EXTRA.md,auth.json,end" "$out"

# A run that leaves a directory without owner write or search permission must not
# stop later starts. One case is a mode 500 directory holding a file; the other is
# a deeper tree with mode 000 and 500 levels and a symlink to an outside directory,
# whose target must keep its mode and content.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -- sh -c '
	h=/home/kelos/.codex
	mkdir $h/locked && printf "x\n" > $h/locked/f && chmod 500 $h/locked
	mkdir -p $h/deep/a/b/c/d /tmp/out2 && printf "x\n" > $h/deep/a/b/c/d/f && printf "keep\n" > /tmp/out2/k
	ln -s /tmp/out2 $h/deep/a/b/link && chmod 500 /tmp/out2
	chmod 500 $h/deep/a/b/c/d && chmod 000 $h/deep/a/b/c && chmod 500 $h/deep/a/b && chmod 000 $h/deep/a
	/kelos_entrypoint.sh; echo "rc=$?"
	/kelos_entrypoint.sh; echo "rc2=$?"
	echo "entries=$(LC_ALL=C ls -A $h | tr "\n" ",")end"
	echo "outside=$(stat -c %a /tmp/out2) $(cat /tmp/out2/k)"' 2>&1)
assert_contains "locked directories: the start succeeds" "rc=0" "$out"
assert_contains "locked directories: the next start succeeds" "rc2=0" "$out"
assert_contains "locked directories: both trees are gone" "entries=config.toml,end" "$out"
assert_contains "locked directories: the symlink target keeps its mode and content" "outside=500 keep" "$out"

# auth.json is checked against CODEX_AUTH_JSON. The JSON below is fake and holds no
# real token. A file with the same account and refreshed tokens is kept byte for
# byte; an invalid file, a file with missing token fields, another account, or an
# added API key is replaced by CODEX_AUTH_JSON with mode 600. The log names the
# reason and never a token value.
secret='{"auth_mode":"chatgpt","OPENAI_API_KEY":null,"tokens":{"id_token":"id-from-secret","access_token":"at-from-secret","refresh_token":"rt-from-secret","account_id":"acct-a"}}'
# shellcheck disable=SC2016 # expands in the container
auth_case() {
	kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -e "CODEX_AUTH_JSON=$secret" -e "OLD_AUTH=$1" -- sh -c '
		f=/home/kelos/.codex/auth.json
		printf "%s" "$OLD_AUTH" > $f && chmod 644 $f
		before=$(sha256sum < $f)
		/kelos_entrypoint.sh; echo "rc=$?"
		if [ "$(sha256sum < $f)" = "$before" ]; then echo auth=kept
		elif printf "%s" "$CODEX_AUTH_JSON" | cmp -s - $f; then echo auth=reseeded
		else echo auth=other; fi
		echo "mode=$(stat -c %a $f)"
		echo "entries=$(LC_ALL=C ls -A /home/kelos/.codex | tr "\n" ",")end"
		echo "checkdirs=$(ls -d /tmp/codex-auth-check.* 2>/dev/null | wc -l)"' 2>&1
}
out=$(auth_case '{"auth_mode":"chatgpt","OPENAI_API_KEY":null,"tokens":{"id_token":"'"$fake_jwt"'","access_token":"at-rotated","refresh_token":"rt-rotated","account_id":"acct-a"},"last_refresh":"2020-01-01T00:00:00Z"}')
assert_contains "auth same account: the start succeeds" "rc=0" "$out"
assert_contains "auth same account: refreshed tokens are kept byte for byte" "auth=kept" "$out"
assert_absent "auth same account: no reseed is logged" "$out" "rc=0" "reseeded auth.json"
assert_contains "auth same account: a kept file at mode 644 comes out 600" "mode=600" "$out"
assert_contains "auth same account: codex login status leaves nothing in the home" "entries=auth.json,config.toml,end" "$out"
assert_contains "auth same account: the check directory is removed" "checkdirs=0" "$out"
out=$(auth_case '{"tokens": {"id_token": "id-x", "access_token"')
assert_contains "auth invalid JSON: reseeded from CODEX_AUTH_JSON" "auth=reseeded" "$out"
assert_contains "auth invalid JSON: the log says why" "reseeded auth.json from CODEX_AUTH_JSON because it is not a single JSON object" "$out"
assert_contains "auth invalid JSON: the new file has mode 600" "mode=600" "$out"
assert_contains "auth invalid JSON: no temp file is left" "entries=auth.json,config.toml,end" "$out"
out=$(auth_case '{"auth_mode":"chatgpt","OPENAI_API_KEY":null,"tokens":{"id_token":"id-other","access_token":"at-other","refresh_token":"rt-other","account_id":"acct-b"}}')
assert_contains "auth other account: reseeded from CODEX_AUTH_JSON" "auth=reseeded" "$out"
assert_contains "auth other account: the log says why" "because its tokens.account_id differs from CODEX_AUTH_JSON" "$out"
assert_absent "auth other account: no token value is printed" "$out" "auth=reseeded" "id-other" "at-other" "rt-other" "acct-b" "from-secret"
out=$(auth_case '{"auth_mode":"chatgpt","OPENAI_API_KEY":null,"tokens":{"id_token":"id-rotated","access_token":"at-rotated","account_id":"acct-a"}}')
assert_contains "auth missing refresh_token: reseeded from CODEX_AUTH_JSON" "auth=reseeded" "$out"
assert_contains "auth missing refresh_token: the log says why" "because it lacks tokens.id_token, tokens.access_token or tokens.refresh_token" "$out"
out=$(auth_case '{"auth_mode":"chatgpt","OPENAI_API_KEY":"sk-fake","tokens":{"id_token":"id-rotated","access_token":"at-rotated","refresh_token":"rt-rotated","account_id":"acct-a"}}')
assert_contains "auth with an added API key: reseeded from CODEX_AUTH_JSON" "auth=reseeded" "$out"
assert_contains "auth with an added API key: the log names the field" "because its OPENAI_API_KEY differs from CODEX_AUTH_JSON" "$out"
assert_absent "auth with an added API key: the key is not printed" "$out" "auth=reseeded" "sk-fake"
# Files that pass the field checks but that Codex refuses to load: an id_token that
# is not a JWT, and a duplicate key (jq keeps the last value, Codex rejects the file).
out=$(auth_case '{"auth_mode":"chatgpt","OPENAI_API_KEY":null,"tokens":{"id_token":"id-not-a-jwt","access_token":"at-rotated","refresh_token":"rt-rotated","account_id":"acct-a"}}')
assert_contains "auth id_token not a JWT: reseeded from CODEX_AUTH_JSON" "auth=reseeded" "$out"
assert_contains "auth id_token not a JWT: the log says why" "because codex login status rejects it (exit 1)" "$out"
assert_contains "auth id_token not a JWT: no check directory or tmp is left in the home" "entries=auth.json,config.toml,end" "$out"
assert_absent "auth id_token not a JWT: no token value is printed" "$out" "auth=reseeded" "id-not-a-jwt" "rt-rotated"
out=$(auth_case '{"auth_mode":"chatgpt","OPENAI_API_KEY":null,"OPENAI_API_KEY":null,"tokens":{"id_token":"'"$fake_jwt"'","access_token":"at-rotated","refresh_token":"rt-rotated","account_id":"acct-a"}}')
assert_contains "auth duplicate OPENAI_API_KEY: reseeded from CODEX_AUTH_JSON" "auth=reseeded" "$out"
assert_contains "auth duplicate OPENAI_API_KEY: the log says why" "because codex login status rejects it (exit 1)" "$out"
# When the load check cannot run, the existing file is kept: a codex that does not
# finish within the 20 s timeout, a temp directory that cannot be made, and a copy
# that fails. The file has an id_token that is not a JWT, so a check that did run
# would replace it. The Codex entrypoint is run directly so that PATH and TMPDIR can
# point at stubs; the dispatcher's guard would refuse them.
rejected_auth='{"auth_mode":"chatgpt","OPENAI_API_KEY":null,"tokens":{"id_token":"id-not-a-jwt","access_token":"at-rotated","refresh_token":"rt-rotated","account_id":"acct-a"}}'
# shellcheck disable=SC2016 # expands in the container
auth_unchecked_case() {
	kr -e KELOS_SESSION_SETUP_ONLY=1 -e CODEX_HOME=/home/kelos/.codex -e "CODEX_AUTH_JSON=$secret" -e "OLD_AUTH=$rejected_auth" -e "CASE=$1" -- sh -c '
		f=/home/kelos/.codex/auth.json
		printf "%s" "$OLD_AUTH" > $f
		before=$(sha256sum < $f)
		mkdir -p /tmp/stub
		tmpdir=/tmp
		case "$CASE" in
		timeout) printf "#!/bin/sh\nexec sleep 60\n" > /tmp/stub/codex ;;
		mktemp) tmpdir=/nonexistent ;;
		cp) printf "#!/bin/sh\nexit 1\n" > /tmp/stub/cp ;;
		esac
		chmod 755 /tmp/stub/* 2>/dev/null
		start=$(date +%s)
		env PATH="/tmp/stub:$PATH" TMPDIR="$tmpdir" /kelos_entrypoint_codex.sh; echo "rc=$?"
		echo "elapsed=$(($(date +%s) - start))"
		[ "$(sha256sum < $f)" = "$before" ] && echo auth=kept || echo auth=changed
		echo "checkdirs=$(ls -d /tmp/codex-auth-check.* 2>/dev/null | wc -l)"' 2>&1
}
for case in timeout mktemp cp; do
	out=$(auth_unchecked_case "$case")
	assert_contains "auth check cannot run ($case): the start succeeds" "rc=0" "$out"
	assert_contains "auth check cannot run ($case): auth.json is kept byte for byte" "auth=kept" "$out"
	assert_contains "auth check cannot run ($case): the log says the file was kept" "could not check auth.json, kept the existing file" "$out"
	assert_contains "auth check cannot run ($case): no check directory is left" "checkdirs=0" "$out"
	assert_absent "auth check cannot run ($case): no token value is printed" "$out" "rc=" "id-not-a-jwt" "rt-rotated" "from-secret"
	[ "$case" != timeout ] || assert_contains "auth check cannot run (timeout): the log names the timeout" "did not finish within 20 s" "$out"
done
# Without CODEX_AUTH_JSON an existing auth.json is left as it is, even when invalid.
# shellcheck disable=SC2016 # expands in the container
assert_eq "auth without CODEX_AUTH_JSON: the file is kept" "not json" "$(kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -- sh -c '
	printf "not json" > /home/kelos/.codex/auth.json
	/kelos_entrypoint.sh >/dev/null 2>&1
	cat /home/kelos/.codex/auth.json' 2>&1)"

# A real start, not setup only, gets a clean home before codex runs. A stub codex
# prints what it finds. user 0 lets the test replace the binary; the dispatcher then
# runs as UID 61100.
# shellcheck disable=SC2016 # expands in the stub
codex_stub='#!/bin/sh
h=${CODEX_HOME:-$HOME/.codex}
echo "stub-entries=$(LC_ALL=C ls -A "$h" | tr "\n" ",")end" >&2
cat "$h/config.toml" >&2 2>/dev/null
exit 0
'
# shellcheck disable=SC2016 # expands in the container
out=$(kr --user 0 -e KELOS_AGENT_TYPE=codex -e HOME=/home/kelos -e 'KELOS_AGENTS_MD=fresh rules' -e "STUB=$codex_stub" -- sh -c '
	h=/home/kelos/.codex
	printf "%s" "$STUB" > /usr/local/bin/codex && chmod 755 /usr/local/bin/codex
	printf "model = \"planted\"\n" > $h/config.toml && printf "planted\n" > $h/EXTRA.md && chown -R 61100:61100 $h
	setpriv --reuid 61100 --regid 61100 --clear-groups /kelos_entrypoint.sh hi; echo "rc=$?"' 2>&1)
assert_contains "real start: the entrypoint exits 0" "rc=0" "$out"
assert_contains "real start: codex sees only AGENTS.md" "stub-entries=AGENTS.md,end" "$out"
assert_absent "real start: codex sees no planted config.toml" "$out" "stub-entries=" "planted"

# CODEX_HOME must be set, must be /home/kelos/.codex, and must not be a symlink. The
# dispatcher sets it after its guard; the entrypoint run directly checks it itself.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -- sh -c '
	rm -rf /home/kelos/.codex && mkdir -p /tmp/real && printf "x\n" > /tmp/real/EXTRA.md
	ln -s /tmp/real /home/kelos/.codex
	/kelos_entrypoint.sh; echo "rc=$?"
	echo "real=$(LC_ALL=C ls -A /tmp/real | tr "\n" ",")end"' 2>&1)
assert_contains "symlinked CODEX_HOME: refused with exit 78" "rc=78" "$out"
assert_contains "symlinked CODEX_HOME: the refusal names it" ".codex is a symlink" "$out"
assert_contains "symlinked CODEX_HOME: the link target is untouched" "real=EXTRA.md,end" "$out"
# shellcheck disable=SC2016 # expands in the container
out=$(kr -e KELOS_SESSION_SETUP_ONLY=1 -- sh -c '
	printf "x\n" > /home/kelos/.codex/EXTRA.md
	/kelos_entrypoint_codex.sh; echo "rc=$?"
	echo "entries=$(LC_ALL=C ls -A /home/kelos/.codex | tr "\n" ",")end"' 2>&1)
assert_contains "codex entrypoint refuses an unset CODEX_HOME" "rc=78" "$out"
assert_contains "the refusal says CODEX_HOME is not set" "CODEX_HOME is not set" "$out"
assert_contains "unset CODEX_HOME: nothing was removed" "entries=EXTRA.md,end" "$out"
out=$(kr -e KELOS_SESSION_SETUP_ONLY=1 -e CODEX_HOME=/tmp/codex -- /kelos_entrypoint_codex.sh 2>&1)
rc=$?
if [ "$rc" -eq 78 ]; then pass "codex entrypoint refuses another CODEX_HOME"; else fail "codex entrypoint refuses another CODEX_HOME" "exit $rc"; fi
assert_contains "the refusal names the CODEX_HOME value" "CODEX_HOME is /tmp/codex" "$out"

# Proxy CA: the bundle is the system bundle plus the proxy CA, and the variables point at it.
# The setup command (allowed for Codex) prints what the agent would see.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -- sh -c '
	openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 1 -subj /CN=test-proxy-ca -keyout /dev/null -out /tmp/proxy-ca.crt 2>/dev/null
	export PROXY_CA_FILE=/tmp/proxy-ca.crt
	export KELOS_SETUP_COMMAND="[\"sh\",\"-c\",\"echo git=\$GIT_SSL_CAINFO; echo ssl=\$SSL_CERT_FILE; echo node=\$NODE_EXTRA_CA_CERTS; echo sys=\$(grep -c BEGIN /etc/ssl/certs/ca-certificates.crt); echo bundle=\$(grep -c BEGIN \$GIT_SSL_CAINFO); grep -c test-proxy-ca-never \$GIT_SSL_CAINFO >/dev/null; cmp /tmp/proxy-ca.crt \$NODE_EXTRA_CA_CERTS && echo nodecmp=same\"]"
	/kelos_entrypoint.sh' 2>&1)
git_path=$(printf '%s\n' "$out" | sed -n 's/^git=//p')
assert_eq "SSL_CERT_FILE equals GIT_SSL_CAINFO" "$git_path" "$(printf '%s\n' "$out" | sed -n 's/^ssl=//p')"
assert_eq "NODE_EXTRA_CA_CERTS is the proxy CA file" "/tmp/proxy-ca.crt" "$(printf '%s\n' "$out" | sed -n 's/^node=//p')"
sys_count=$(printf '%s\n' "$out" | sed -n 's/^sys=//p')
bundle_count=$(printf '%s\n' "$out" | sed -n 's/^bundle=//p')
assert_eq "bundle has the system CAs plus one" "$((sys_count + 1))" "$bundle_count"
case "$git_path" in /tmp/kelos-ca.*/ca-bundle.crt) pass "bundle is in a writable temp directory" ;; *) fail "bundle is in a writable temp directory" "[$git_path]" ;; esac
# A missing proxy CA file is refused.
kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -e PROXY_CA_FILE=/nonexistent -- /kelos_entrypoint.sh >/dev/null 2>&1
assert_eq "missing PROXY_CA_FILE is refused" "78" "$?"

# Exported bash functions: bash would import them and replace jq, compgen or claude.
# shellcheck disable=SC2016 # expands in the container
for fn in jq compgen claude git; do
	# dash drops names that are not shell identifiers, so env sets the variable at the exec.
	out=$(kr -e KELOS_AGENT_TYPE=claude-code -e KELOS_SESSION_SETUP_ONLY=1 -- sh -c '
		mkdir -p ~/.claude && printf "{\"apiKeyHelper\": \"x\"}" > ~/.claude/settings.json
		exec env "BASH_FUNC_'"$fn"'%%=() { :; }" /kelos_entrypoint.sh' 2>&1)
	rc=$?
	if [ "$rc" -eq 78 ]; then pass "BASH_FUNC_$fn is refused"; else fail "BASH_FUNC_$fn is refused" "exit $rc"; fi
	assert_contains "refusal names the exported function" "BASH_FUNC" "$out"
done
# A jq function replaced by a no-op must not let a settings file through, so the dispatcher refuses.
kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -e 'BASH_FUNC_jq%%=() { :; }' -- /kelos_entrypoint.sh >/dev/null 2>&1
assert_eq "BASH_FUNC_jq is refused for codex too" "78" "$?"
# The dispatcher itself does not import functions (bash -p).
assert_eq "dispatcher shebang is bash -p" "#!/bin/bash -p" "$(kr -- head -n 1 /kelos_entrypoint.sh)"
assert_eq "bash -p does not import an exported function" "file" "$(kr -e 'BASH_FUNC_jq%%=() { :; }' -- bash -p -c 'type -t jq')"

# Symlinked settings files, dangling or not.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -e KELOS_AGENT_TYPE=claude-code -e KELOS_SESSION_SETUP_ONLY=1 -- sh -c '
	mkdir -p ~/.claude && ln -s ~/.claude/CLAUDE.md ~/.claude/settings.json
	/kelos_entrypoint.sh' 2>&1)
rc=$?
if [ "$rc" -eq 78 ]; then pass "dangling user settings.json symlink is refused"; else fail "dangling user settings.json symlink is refused" "exit $rc"; fi
assert_contains "refusal names the symlink" "symlink" "$out"
# shellcheck disable=SC2016 # expands in the container
kr -e KELOS_AGENT_TYPE=claude-code -e KELOS_SESSION_SETUP_ONLY=1 -- sh -c '
	mkdir -p /tmp/repo/.claude && cd /tmp/repo && git init -q \
	&& ln -s /tmp/repo/.claude/CLAUDE.md .claude/settings.json
	/kelos_entrypoint.sh' >/dev/null 2>&1
assert_eq "dangling project settings.json symlink is refused" "78" "$?"
# shellcheck disable=SC2016 # expands in the container
kr -e KELOS_AGENT_TYPE=claude-code -e KELOS_SESSION_SETUP_ONLY=1 -- sh -c '
	mkdir -p /tmp/repo/.claude && cd /tmp/repo && git init -q \
	&& ln -s /tmp/nowhere .claude/settings.local.json
	/kelos_entrypoint.sh' >/dev/null 2>&1
assert_eq "dangling project settings.local.json symlink is refused" "78" "$?"
# shellcheck disable=SC2016 # expands in the container
kr -e KELOS_AGENT_TYPE=claude-code -e KELOS_SESSION_SETUP_ONLY=1 -- sh -c '
	mkdir -p /tmp/real && printf "{}" > /tmp/real/settings.json && rm -rf ~/.claude && ln -s /tmp/real ~/.claude
	/kelos_entrypoint.sh' >/dev/null 2>&1
assert_eq "symlinked .claude directory is refused" "78" "$?"

# The Kelos entrypoint writes KELOS_AGENTS_MD after the first guard. With CLAUDE.md
# linked to a valid settings.json, the write fills the settings file, and the
# wrapper must refuse before claude starts. A prompt is given so the entrypoint
# gets as far as running claude.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -e KELOS_AGENT_TYPE=claude-code -e 'KELOS_AGENTS_MD={"apiKeyHelper":"/bin/true"}' -- sh -c '
	mkdir -p ~/.claude && printf "{}" > ~/.claude/settings.json && ln -s ~/.claude/settings.json ~/.claude/CLAUDE.md
	/kelos_entrypoint.sh hi; echo "exit=$?"; cat ~/.claude/settings.json' 2>&1)
assert_contains "settings file was filled by the entrypoint write" '"apiKeyHelper"' "$out"
assert_contains "wrapper refuses before claude starts" "exit=78" "$out"
assert_contains "wrapper names the key" "contains apiKeyHelper" "$out"
# The wrapper is the claude that the entrypoint finds first once the dispatcher has set PATH.
# shellcheck disable=SC2016 # expands in the container
assert_eq "wrapper is first on PATH after the dispatcher" "/usr/local/lib/kelos/bin/claude" "$(kr -e KELOS_AGENT_TYPE=claude-code -e KELOS_SESSION_SETUP_ONLY=1 -e 'KELOS_SETUP_COMMAND_UNUSED=1' -- sh -c '
	PATH=/usr/local/lib/kelos/bin:$PATH command -v claude')"

# Loader and Node option variables, and PATH.
for var in LD_PRELOAD LD_LIBRARY_PATH LD_AUDIT NODE_OPTIONS; do
	for type in claude-code codex; do
		out=$(kr -e "KELOS_AGENT_TYPE=$type" -e KELOS_SESSION_SETUP_ONLY=1 -e "$var=x" -- /kelos_entrypoint.sh 2>&1)
		rc=$?
		if [ "$rc" -eq 78 ]; then pass "$var is refused for $type"; else fail "$var is refused for $type" "exit $rc"; fi
		assert_contains "refusal names $var for $type" "$var" "$out"
	done
done
# shellcheck disable=SC2016 # expands in the container
assert_eq "PATH with an extra first entry is refused" "78" "$(kr -e KELOS_AGENT_TYPE=claude-code -e KELOS_SESSION_SETUP_ONLY=1 -- sh -c 'PATH=/tmp/evil:$PATH /kelos_entrypoint.sh >/dev/null 2>&1; echo $?')"
assert_eq "short PATH is refused" "78" "$(
	kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -e PATH=/usr/bin:/bin -- /kelos_entrypoint.sh >/dev/null 2>&1
	echo $?
)"
# shellcheck disable=SC2016 # expands in the container
assert_eq "image PATH plus extra entries after it is accepted" "0" "$(kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -- sh -c 'PATH=$PATH:/opt/extra /kelos_entrypoint.sh >/dev/null 2>&1; echo $?')"
# shellcheck disable=SC2016 # expands in the container
assert_eq "wrapper directory in front of the image PATH is accepted" "0" "$(kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -- sh -c 'PATH=/usr/local/lib/kelos/bin:$PATH /kelos_entrypoint.sh >/dev/null 2>&1; echo $?')"
# shellcheck disable=SC2016 # expands in the container
assert_eq "wrapper refuses a changed PATH" "78" "$(kr -- sh -c 'PATH=/tmp/evil:$PATH /usr/local/lib/kelos/bin/claude --version >/dev/null 2>&1; echo $?')"

# kelos-capture is built from source for this image's architecture: a static ELF
# executable whose header matches the machine, and it runs (kelos-capture reads stdin).
# shellcheck disable=SC2016 # expands in the container
assert_eq "kelos-capture is a static binary for this architecture" "ok" "$(kr -- sh -c '
	case "$(uname -m)" in
	x86_64) arch="x86-64" ;;
	aarch64) arch="ARM aarch64" ;;
	esac
	info=$(file /kelos/kelos-capture)
	case "$info" in
	*"ELF 64-bit"*"$arch"*"statically linked"*) echo ok ;;
	esac')"

# KELOS_MCP_SERVERS starts a command after the guards, so only an empty value passes.
out=$(kr -e KELOS_AGENT_TYPE=claude-code -e KELOS_SESSION_SETUP_ONLY=1 -e 'KELOS_MCP_SERVERS={"mcpServers":{"x":{"command":"/bin/sh"}}}' -- /kelos_entrypoint.sh 2>&1)
rc=$?
if [ "$rc" -eq 78 ]; then pass "KELOS_MCP_SERVERS is refused for claude"; else fail "KELOS_MCP_SERVERS is refused for claude" "exit $rc"; fi
assert_contains "refusal names KELOS_MCP_SERVERS" "KELOS_MCP_SERVERS" "$out"
kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -e 'KELOS_MCP_SERVERS={"mcpServers":{}}' -- /kelos_entrypoint.sh >/dev/null 2>&1
assert_eq "KELOS_MCP_SERVERS is refused for codex" "78" "$?"
kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -e KELOS_MCP_SERVERS= -- /kelos_entrypoint.sh >/dev/null 2>&1
assert_eq "an empty KELOS_MCP_SERVERS is accepted" "0" "$?"

# PATH entries: empty, relative and .. components are refused, wherever they sit.
# shellcheck disable=SC2016 # the PATH values expand in the container
for bad in '$PATH:' '$PATH::/opt/x' ':$PATH' '$PATH:.' '$PATH:..' '$PATH:rel/dir' '$PATH:/opt/../tmp' '$PATH:/opt/./x'; do
	# shellcheck disable=SC2016 # expands in the container
	assert_eq "PATH $bad is refused" "78" "$(kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -- sh -c "PATH=\"$bad\" /kelos_entrypoint.sh >/dev/null 2>&1; echo \$?")"
done

# The wrapper starts claude under env -i with an allowlist. user 0 lets the test put an
# env-printing stub in place of the real binary inside this throwaway container.
# shellcheck disable=SC2016 # expands in the container
allow=$(kr -- bash -p -c '. /usr/local/lib/kelos/guard.sh; printf "%s\n" "${claude_env_allowlist[@]}"')
set --
# HOME may only be /home/kelos (the guard refuses anything else), so it gets
# that value; every other allowlisted variable gets a marker value.
val() { if [ "$1" = HOME ]; then echo /home/kelos; else echo "v_$1"; fi; }
for v in $allow; do set -- "$@" -e "$v=$(val "$v")"; done
# shellcheck disable=SC2016 # expands in the container
stub='printf "#!/bin/sh\nexec /usr/bin/env\n" > /usr/local/bin/claude; exec /usr/local/lib/kelos/bin/claude'
seen=$(kr --user 0 "$@" -e BUN_OPTIONS=--preload=/tmp/p.js -e UNKNOWN_VAR=1 -e OPENAI_API_KEY=x -e NODE_PATH=/tmp -- sh -c "$stub" 2>&1)
missing=""
for v in $allow; do
	case "
$seen
" in
	*"
$v=$(val "$v")
"*) ;;
	*) missing="$missing $v" ;;
	esac
done
assert_eq "every allowlisted variable reaches claude" "" "$missing"
assert_absent "BUN_OPTIONS, an unknown variable and others are dropped" "$seen" "PATH=" BUN_OPTIONS UNKNOWN_VAR OPENAI_API_KEY NODE_PATH
assert_contains "claude gets the fixed image PATH" "PATH=/home/kelos/.local/bin:/usr/local/go/bin:/opt/cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" "$seen"
assert_absent "the wrapper directory is not in claude's PATH" "$seen" "PATH=" "/usr/local/lib/kelos/bin"
# BUN_OPTIONS also fails to reach claude through the dispatcher path.
assert_eq "the guard still passes with BUN_OPTIONS set (it is dropped, not refused)" "0" "$(
	kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -e BUN_OPTIONS=x -- /kelos_entrypoint.sh >/dev/null 2>&1
	echo $?
)"

# HOME and CLAUDE_CONFIG_DIR changes, Codex credential variables and CODEX_HOME are refused, and
# the claude wrapper passes the settings-source flags and the repository CLAUDE.md.
out=$(kr -e KELOS_AGENT_TYPE=claude-code -e KELOS_SESSION_SETUP_ONLY=1 -e HOME=/workspace -- /kelos_entrypoint.sh 2>&1)
rc=$?
if [ "$rc" -eq 78 ]; then pass "HOME other than /home/kelos is refused"; else fail "HOME other than /home/kelos is refused" "exit $rc"; fi
out=$(kr -e KELOS_AGENT_TYPE=claude-code -e KELOS_SESSION_SETUP_ONLY=1 -e CLAUDE_CONFIG_DIR=/workspace/.claude -- /kelos_entrypoint.sh 2>&1)
rc=$?
if [ "$rc" -eq 78 ]; then pass "CLAUDE_CONFIG_DIR is refused"; else fail "CLAUDE_CONFIG_DIR is refused" "exit $rc"; fi
for k in CODEX_API_KEY OPENAI_API_KEY openai_api_key; do
	out=$(kr -e KELOS_AGENT_TYPE=codex -e "$k=x" -- /kelos_entrypoint.sh 2>&1)
	rc=$?
	if [ "$rc" -eq 78 ]; then pass "codex: $k is refused"; else fail "codex: $k is refused" "exit $rc"; fi
done
if kr -- grep -q -- '--setting-sources user --strict-mcp-config' /usr/local/lib/kelos/bin/claude; then pass "wrapper passes --setting-sources user --strict-mcp-config"; else fail "wrapper passes --setting-sources user --strict-mcp-config" "flags missing"; fi
for k in CODEX_ACCESS_TOKEN CODEX_REFRESH_TOKEN_URL_OVERRIDE; do
	out=$(kr -e KELOS_AGENT_TYPE=codex -e "$k=x" -- /kelos_entrypoint.sh 2>&1)
	rc=$?
	if [ "$rc" -eq 78 ]; then pass "codex: $k is refused"; else fail "codex: $k is refused" "exit $rc"; fi
done
out=$(kr -e KELOS_AGENT_TYPE=codex -e CODEX_HOME=/workspace/.codex -- /kelos_entrypoint.sh 2>&1)
rc=$?
if [ "$rc" -eq 78 ]; then pass "codex: CODEX_HOME elsewhere is refused"; else fail "codex: CODEX_HOME elsewhere is refused" "exit $rc"; fi
# shellcheck disable=SC2016 # expands in the container
seen=$(kr --user 0 -e HOME=/home/kelos -e CLAUDE_CODE_OAUTH_TOKEN=x -- sh -c 'printf "#!/bin/sh\nprintf \"%%s\\n\" \"\$@\"\n" > /usr/local/bin/claude; mkdir -p /tmp/r && cd /tmp/r && echo rules > CLAUDE.md && /usr/local/lib/kelos/bin/claude -p hi' 2>&1)
assert_contains "wrapper passes the repo CLAUDE.md as prompt text" "--append-system-prompt-file" "$seen"

# The Task's git identity reaches git commits run by claude.
# shellcheck disable=SC2016 # expands in the container
seen=$(kr --user 0 -e HOME=/home/kelos -e CLAUDE_CODE_OAUTH_TOKEN=x -e GIT_AUTHOR_NAME=n -e GIT_AUTHOR_EMAIL=e@x -e GIT_COMMITTER_NAME=n -e GIT_COMMITTER_EMAIL=e@x -- sh -c 'printf "#!/bin/sh\nexec /usr/bin/env\n" > /usr/local/bin/claude; exec /usr/local/lib/kelos/bin/claude' 2>&1)
for v in GIT_AUTHOR_NAME=n GIT_AUTHOR_EMAIL=e@x GIT_COMMITTER_NAME=n GIT_COMMITTER_EMAIL=e@x; do
	assert_contains "git identity passes: $v" "$v" "$seen"
done

# push-sidecar. Argument and environment checks.
for case in "PUSH_URL unset|PUSH_BRANCH=task" "PUSH_URL is http|PUSH_URL=http://github.com/o/r.git PUSH_BRANCH=task" "PUSH_URL has credentials|PUSH_URL=https://u:p@github.com/o/r.git PUSH_BRANCH=task" "PUSH_URL is another host|PUSH_URL=https://example.com/o/r.git PUSH_BRANCH=task" "PUSH_URL is a local path without the test switch|PUSH_URL=/tmp/r.git PUSH_BRANCH=task" "PUSH_BRANCH unset|PUSH_URL=https://github.com/o/r.git" "bad branch name|PUSH_URL=https://github.com/o/r.git PUSH_BRANCH=-x" "branch with a tilde|PUSH_URL=https://github.com/o/r.git PUSH_BRANCH=a~b" "missing token file|PUSH_URL=https://github.com/o/r.git PUSH_BRANCH=task KELOS_GITHUB_TOKEN_FILE=/nonexistent" "bad interval|PUSH_URL=https://github.com/o/r.git PUSH_BRANCH=task KELOS_GITHUB_TOKEN_FILE=/etc/hostname PUSH_INTERVAL=abc"; do
	name=${case%%|*}
	vars=${case#*|}
	# shellcheck disable=SC2086 # the variable list is split on purpose
	out=$(kr -- env $vars /usr/local/bin/push-sidecar 2>&1)
	rc=$?
	if [ "$rc" -eq 1 ]; then pass "push-sidecar exits 1: $name"; else fail "push-sidecar exits 1: $name" "exit $rc"; fi
	assert_contains "push-sidecar prints push-failed: $name" "push-failed:" "$out"
done

# push-sidecar against a local bare repository. The token file is never used by a
# file remote; these tests cover commits, identity, SIGTERM, failures and hooks.
ps_setup='
set -e
rm -rf /tmp/ps && mkdir -p /tmp/ps && cd /tmp/ps
git init -q --bare remote.git
git init -q -b task work
git -C work -c user.name=i -c user.email=i@x commit -q --allow-empty -m init
git -C work push -q /tmp/ps/remote.git task
printf secret-token > /tmp/ps/token
export PUSH_URL=/tmp/ps/remote.git PUSH_ALLOW_FILE_REMOTE=1 PUSH_REPO=/tmp/ps/work PUSH_BRANCH=task KELOS_GITHUB_TOKEN_FILE=/tmp/ps/token GIT_AUTHOR_NAME=Bot GIT_AUTHOR_EMAIL=bot@example.com
set +e
'
# SIGTERM makes a final commit and push, with the Task identity.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -- bash -c "$ps_setup"'
/usr/local/bin/push-sidecar >/tmp/ps/out 2>&1 &
pid=$!
sleep 3
echo hello > work/f.txt
kill -TERM $pid
wait $pid
echo "rc=$?"
cat /tmp/ps/out
git -C remote.git log task -1 --format="log=%an <%ae>|%cn <%ce>|%s"
echo "file=$(git -C remote.git show task:f.txt)"' 2>&1)
assert_contains "push-sidecar exits 0 after SIGTERM" "rc=0" "$out"
assert_contains "push-sidecar prints push-ok" "push-ok" "$out"
assert_contains "WIP commit has the Task identity as author and committer" "log=Bot <bot@example.com>|Bot <bot@example.com>|agent WIP" "$out"
assert_contains "the pushed branch holds the new file" "file=hello" "$out"
# Nothing to commit is a success.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -- bash -c "$ps_setup"'
/usr/local/bin/push-sidecar >/tmp/ps/out 2>&1 &
pid=$!
sleep 3
kill -TERM $pid
wait $pid
echo "rc=$?"
cat /tmp/ps/out
echo "count=$(git -C remote.git rev-list --count task)"' 2>&1)
assert_contains "nothing to commit exits 0" "rc=0" "$out"
assert_contains "nothing to commit prints push-ok" "push-ok" "$out"
assert_contains "nothing to commit adds no commit" "count=1" "$out"
# A periodic push happens before SIGTERM.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -- bash -c "$ps_setup"'
PUSH_INTERVAL=1 /usr/local/bin/push-sidecar >/tmp/ps/out 2>&1 &
pid=$!
sleep 2
echo periodic > work/p.txt
for i in $(seq 1 40); do git -C remote.git show task:p.txt >/dev/null 2>&1 && break; sleep 1; done
echo "before-term=$(git -C remote.git show task:p.txt 2>&1)"
kill -TERM $pid
wait $pid
echo "rc=$?"' 2>&1)
assert_contains "periodic push lands before SIGTERM" "before-term=periodic" "$out"
# A refused push is push-failed, exit 1, and the token is not printed.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -- bash -c "$ps_setup"'
printf "#!/bin/sh\necho \"GH013 refused secret-token\" >&2\nexit 1\n" > remote.git/hooks/pre-receive
chmod +x remote.git/hooks/pre-receive
/usr/local/bin/push-sidecar >/tmp/ps/out 2>&1 &
pid=$!
sleep 3
echo hello > work/f.txt
kill -TERM $pid
wait $pid
echo "rc=$?"
cat /tmp/ps/out' 2>&1)
assert_contains "refused push exits 1" "rc=1" "$out"
assert_contains "refused push prints push-failed with the reason" "push-failed:" "$out"
assert_contains "the reason carries the remote message" "GH013 refused" "$out"
assert_absent "the token is masked in the output" "$out" "rc=1" "secret-token"
# Repository hooks do not run in the sidecar.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -- bash -c "$ps_setup"'
printf "#!/bin/sh\ntouch /tmp/ps/hook-ran\n" > work/.git/hooks/pre-commit
chmod +x work/.git/hooks/pre-commit
/usr/local/bin/push-sidecar >/tmp/ps/out 2>&1 &
pid=$!
sleep 3
echo hello > work/f.txt
kill -TERM $pid
wait $pid
echo "rc=$?"
test -e /tmp/ps/hook-ran && echo hook-ran || echo hook-skipped' 2>&1)
assert_contains "the commit succeeds with a pre-commit hook present" "rc=0" "$out"
assert_contains "the pre-commit hook does not run" "hook-skipped" "$out"
# SIGTERM before any repository exists is a failure.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -- bash -c '
printf secret-token > /tmp/tok
PUSH_URL=https://github.com/o/r.git PUSH_REPO=/tmp/none PUSH_BRANCH=task KELOS_GITHUB_TOKEN_FILE=/tmp/tok /usr/local/bin/push-sidecar >/tmp/out 2>&1 &
pid=$!
sleep 3
kill -TERM $pid
wait $pid
echo "rc=$?"
cat /tmp/out' 2>&1)
assert_contains "no repository exits 1" "rc=1" "$out"
assert_contains "no repository is reported" "no git repository" "$out"
# The credential helper reads the token file and the token is not in the process arguments.
# shellcheck disable=SC2016 # expands in the container
assert_eq "push-sidecar source has no token in a URL or argument" "ok" "$(kr -- sh -c '
	grep -q "x-access-token" /usr/local/bin/push-sidecar && ! grep -q "https://[^ ]*@" /usr/local/bin/push-sidecar && echo ok')"
# shellcheck disable=SC2016 # expands in the container
assert_eq "DISABLE_TELEMETRY is in the claude allowlist" "DISABLE_TELEMETRY" "$(kr -- bash -p -c '. /usr/local/lib/kelos/guard.sh; printf "%s\n" "${claude_env_allowlist[@]}"' | grep -x DISABLE_TELEMETRY)"

# Repository config that could start a command or move the token is refused, and
# nothing runs. Each case is "key|value".
for case in "include.path|/tmp/ps/extra" "includeIf.gitdir:/tmp/.path|/tmp/ps/extra" "filter.x.clean|touch /tmp/ps/ran" "core.fsmonitor|touch /tmp/ps/ran" "core.sshCommand|touch /tmp/ps/ran" "core.hooksPath|/tmp/ps/hooks" "core.askPass|/tmp/ps/ask" "gpg.program|/tmp/ps/gpg" "url./tmp/other.insteadOf|/tmp/ps/remote.git" "credential.https://github.com.helper|touch /tmp/ps/ran" "http.proxy|http://127.0.0.1:1" "http.sslVerify|false" "protocol.ext.allow|always" "diff.x.textconv|touch /tmp/ps/ran" "diff.external|touch /tmp/ps/ran" "remote.https://github.com/o/r.pushurl|/tmp/ps/other.git" "remote.origin.pushurl|/tmp/ps/other.git" "remote.origin.proxy|http://127.0.0.1:1" "remote.upstream.url|/tmp/ps/other.git" "push.recurseSubmodules|on-demand" "submodule.recurse|true" "submodule.sub.url|/tmp/ps/other.git"; do
	key=${case%%|*}
	value=${case#*|}
	# shellcheck disable=SC2016 # expands in the container
	out=$(kr -e "CFG_KEY=$key" -e "CFG_VALUE=$value" -- bash -c "$ps_setup"'
git -C work config "$CFG_KEY" "$CFG_VALUE"
/usr/local/bin/push-sidecar >/tmp/ps/out 2>&1 &
pid=$!
sleep 3
echo hello > work/f.txt
kill -TERM $pid
wait $pid
echo "rc=$?"
cat /tmp/ps/out
echo "count=$(git -C remote.git rev-list --count task)"
test -e /tmp/ps/ran && echo ran || echo not-run' 2>&1)
	assert_contains "unsafe config $key is refused" "push-failed: unsafe git config" "$out"
	assert_contains "unsafe config $key: exit 1" "rc=1" "$out"
	assert_contains "unsafe config $key: nothing pushed" "count=1" "$out"
	assert_contains "unsafe config $key: nothing ran" "not-run" "$out"
done
# The credential entries Kelos writes into the repository config are accepted.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -- bash -c "$ps_setup"'
git -C work config credential.helper "!f() { echo password=x; }; f"
git -C work config credential.username x-access-token
/usr/local/bin/push-sidecar >/tmp/ps/out 2>&1 &
pid=$!
sleep 3
echo hello > work/f.txt
kill -TERM $pid
wait $pid
echo "rc=$?"
cat /tmp/ps/out' 2>&1)
assert_contains "credential.helper and credential.username in the repo config are accepted" "rc=0" "$out"
# A helper in the repo config does not run when the sidecar's flags are used.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -e KELOS_GITHUB_TOKEN_FILE=/tmp/ps/token -- bash -c "$ps_setup"'
git -C work config credential.helper "!touch /tmp/ps/helper-ran; true"
git -C work config "credential.https://github.com.helper" "!touch /tmp/ps/helper-ran; true"
helper='"'"'!f() { echo username=x-access-token; echo "password=$(cat "$KELOS_GITHUB_TOKEN_FILE")"; }; f'"'"'
printf "protocol=https\nhost=github.com\n\n" | git -C work -c credential.helper= -c "credential.https://github.com.helper=$helper" credential fill 2>&1 | grep -c "password=secret-token"
test -e /tmp/ps/helper-ran && echo helper-ran || echo helper-not-run' 2>&1)
assert_contains "the flags clear a generic helper from the repo config" "helper-not-run" "$out"

# A stale index.lock does not stop the push of commits the agent already made.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -- bash -c "$ps_setup"'
git -C work -c user.name=a -c user.email=a@x commit -q --allow-empty -m "agent own commit"
touch work/.git/index.lock
echo uncommitted > work/b.txt
/usr/local/bin/push-sidecar >/tmp/ps/out 2>&1 &
pid=$!
sleep 3
start=$(date +%s)
kill -TERM $pid
wait $pid
echo "rc=$?"
echo "elapsed=$(($(date +%s) - start))"
cat /tmp/ps/out
echo "subject=$(git -C remote.git log task -1 --format=%s)"
git -C remote.git show task:b.txt >/dev/null 2>&1 && echo b-pushed || echo b-not-pushed' 2>&1)
assert_contains "lock: the agent's own commit is pushed" "subject=agent own commit" "$out"
assert_contains "lock: the commit failure is reported" "index.lock exists" "$out"
assert_contains "lock: the result is push-failed with exit 1" "rc=1" "$out"
assert_contains "lock: the report says HEAD was pushed" "HEAD was pushed" "$out"
assert_contains "lock: the uncommitted file was not pushed" "b-not-pushed" "$out"
case "$out" in *"elapsed=0"* | *"elapsed=1"* | *"elapsed=2"* | *"elapsed=3"*) pass "lock: the final push is quick" ;; *) fail "lock: the final push is quick" "$out" ;; esac

# A merge, rebase, cherry-pick or revert in progress is pushed as HEAD, uncommitted.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -- bash -c "$ps_setup"'
cd work
git checkout -q -b other
echo o > c.txt && git add c.txt && git -c user.name=a -c user.email=a@x commit -q -m other
git checkout -q task
echo t > c.txt && git add c.txt && git -c user.name=a -c user.email=a@x commit -q -m mine
git -c user.name=a -c user.email=a@x merge other >/dev/null 2>&1
cd /tmp/ps
test -e work/.git/MERGE_HEAD && echo merge-state
/usr/local/bin/push-sidecar >/tmp/ps/out 2>&1 &
pid=$!
sleep 3
kill -TERM $pid
wait $pid
echo "rc=$?"
cat /tmp/ps/out
echo "subjects=$(git -C remote.git log task --format=%s | tr "\n" ",")"' 2>&1)
assert_contains "merge: the repository is in a merge" "merge-state" "$out"
assert_contains "merge: HEAD is pushed with exit 0" "rc=0" "$out"
assert_contains "merge: the output says a merge is in progress" "MERGE_HEAD in progress, not committing; pushing HEAD only" "$out"
assert_absent "merge: no WIP commit was made" "$out" "rc=0" "agent WIP"
for name in rebase-merge rebase-apply CHERRY_PICK_HEAD REVERT_HEAD; do
	# shellcheck disable=SC2016 # expands in the container
	out=$(kr -e "OP=$name" -- bash -c "$ps_setup"'
case "$OP" in rebase-merge | rebase-apply) mkdir work/.git/$OP ;; *) touch work/.git/$OP ;; esac
echo hello > work/f.txt
/usr/local/bin/push-sidecar >/tmp/ps/out 2>&1 &
pid=$!
sleep 3
kill -TERM $pid
wait $pid
echo "rc=$?"
cat /tmp/ps/out
echo "count=$(git -C remote.git rev-list --count task)"' 2>&1)
	assert_contains "$name: reported and not committed" "$name in progress, not committing; pushing HEAD only" "$out"
	assert_contains "$name: no commit was added" "count=1" "$out"
done

# Secret files and large files are not committed; .gitignore is honoured.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -- bash -c "$ps_setup"'
cd work
printf "ignored.txt\n" > .gitignore
echo x > ignored.txt; echo x > normal.txt
for f in .env .env.local key.pem server.key id_rsa id_ed25519 my-credentials.json .npmrc .pypirc .netrc auth.json; do echo secret > "$f"; done
mkdir -p .claude && echo secret > .claude/.credentials.json
head -c 11534336 /dev/zero > big.bin
cd /tmp/ps
/usr/local/bin/push-sidecar >/tmp/ps/out 2>&1 &
pid=$!
sleep 3
kill -TERM $pid
wait $pid
echo "rc=$?"
cat /tmp/ps/out
echo "tree=$(git -C remote.git ls-tree -r --name-only task | tr "\n" ",")"' 2>&1)
assert_contains "excludes: only the plain files are pushed" "tree=.gitignore,normal.txt," "$out"
assert_contains "excludes: the large file is named" "skipped 1 file(s) over 10 MB: big.bin" "$out"
assert_contains "excludes: the push still succeeds" "rc=0" "$out"
assert_contains "the excludes file is in the image" "id_rsa*" "$(kr -- cat /usr/local/share/push-sidecar/excludes)"

# A diff driver with a .gitattributes line is refused, and the sidecar's own diff does
# not run the driver. Without the flags git would run it.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -- bash -c "$ps_setup"'
cd work
git config diff.x.textconv "touch /tmp/ps/ran; cat"
echo "* diff=x" > .gitattributes
echo one > t.txt && git add t.txt .gitattributes
git -c user.name=a -c user.email=a@x commit -q -m base
echo two > t.txt && git add t.txt
git diff --cached --quiet >/dev/null 2>&1
test -e /tmp/ps/ran && echo control-ran || echo control-not-run
rm -f /tmp/ps/ran
git diff --cached --quiet --no-textconv --no-ext-diff
test -e /tmp/ps/ran && echo flags-ran || echo flags-not-run
cd /tmp/ps
git -C work reset -q --hard
/usr/local/bin/push-sidecar >/tmp/ps/out 2>&1 &
pid=$!
sleep 3
kill -TERM $pid
wait $pid
echo "rc=$?"
cat /tmp/ps/out' 2>&1)
assert_contains "textconv: without the flags git runs the driver (control)" "control-ran" "$out"
assert_contains "textconv: with the flags it does not" "flags-not-run" "$out"
assert_contains "textconv: the sidecar refuses diff config" "unsafe git config (diff.x.textconv)" "$out"
# remote.origin.url and remote.origin.fetch, as git clone writes them, are accepted.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -- bash -c "$ps_setup"'
git -C work remote add origin /tmp/ps/remote.git
git -C work config --get-regexp "^remote" | cut -d" " -f1 | tr "\n" ","
/usr/local/bin/push-sidecar >/tmp/ps/out 2>&1 &
pid=$!
sleep 3
echo hello > work/f.txt
kill -TERM $pid
wait $pid
echo "rc=$?"
cat /tmp/ps/out' 2>&1)
assert_contains "the keys git clone writes for origin pass" "remote.origin.url,remote.origin.fetch," "$out"
assert_contains "the push succeeds with a normal origin" "rc=0" "$out"

# A negation in .gitignore or .git/info/exclude does not bring a secret file back.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -- bash -c "$ps_setup"'
cd work
printf "!.env\n!*.pem\n" > .gitignore
printf "!id_rsa\n" >> .git/info/exclude
echo x > normal.txt; echo s > .env; echo s > a.pem; echo s > id_rsa; mkdir sub; echo s > sub/.env
cd /tmp/ps
/usr/local/bin/push-sidecar >/tmp/ps/out 2>&1 &
pid=$!
sleep 3
kill -TERM $pid
wait $pid
echo "rc=$?"
echo "tree=$(git -C remote.git ls-tree -r --name-only task | tr "\n" ",")"' 2>&1)
assert_contains "negations: only the plain files are pushed" "tree=.gitignore,normal.txt," "$out"
assert_contains "negations: the push succeeds" "rc=0" "$out"

# SIGTERM during a slow periodic push stops it and runs the final push at once.
# The remote hook blocks the first push only.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -- bash -c "$ps_setup"'
printf "#!/bin/sh\nif [ ! -e /tmp/ps/slept ]; then touch /tmp/ps/slept; sleep 60; fi\n" > remote.git/hooks/pre-receive
chmod +x remote.git/hooks/pre-receive
echo hello > work/f.txt
PUSH_INTERVAL=1 /usr/local/bin/push-sidecar >/tmp/ps/out 2>&1 &
pid=$!
sleep 4
start=$(date +%s)
kill -TERM $pid
wait $pid
echo "rc=$?"
echo "elapsed=$(($(date +%s) - start))"
cat /tmp/ps/out' 2>&1)
assert_contains "slow periodic push: the stop is announced" "stopped by SIGTERM during a periodic push" "$out"
assert_contains "slow periodic push: the final push succeeds" "rc=0" "$out"
case "$out" in *"elapsed=0"* | *"elapsed=1"* | *"elapsed=2"* | *"elapsed=3"* | *"elapsed=4"* | *"elapsed=5"*) pass "slow periodic push: the exit comes within 5 s of SIGTERM" ;; *) fail "slow periodic push: the exit comes within 5 s of SIGTERM" "$out" ;; esac
assert_contains "the script header states the known limit" "Known limit: the sidecar pushes HEAD" "$(kr -- head -n 40 /usr/local/bin/push-sidecar)"

# A negated directory pattern does not bring back what is inside the directory.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -- bash -c "$ps_setup"'
cd work
printf "!credentials/\n!*.pem\n" > .gitignore
echo x > normal.txt
mkdir credentials dir.pem sub
echo s > credentials/aws.json; echo s > dir.pem/inner.txt; echo s > sub/ok.txt
cd /tmp/ps
/usr/local/bin/push-sidecar >/tmp/ps/out 2>&1 &
pid=$!
sleep 3
kill -TERM $pid
wait $pid
echo "rc=$?"
echo "tree=$(git -C remote.git ls-tree -r --name-only task | tr "\n" ",")"' 2>&1)
assert_contains "folder negations: files under secret-named directories stay out" "tree=.gitignore,normal.txt,sub/ok.txt," "$out"
assert_contains "folder negations: the push succeeds" "rc=0" "$out"

# push is told not to recurse into submodules.
assert_contains "git push supports --no-recurse-submodules" "recurse-submodules" "$(kr -- git push -h 2>&1)"
assert_contains "the sidecar passes --no-recurse-submodules" "push --no-recurse-submodules" "$(kr -- cat /usr/local/bin/push-sidecar)"

# A file name that looks like pathspec magic does not escape the size cap.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -- bash -c "$ps_setup"'
cd work
echo x > normal.txt
head -c 11534336 /dev/zero > ":(glob)z.bin"
cd /tmp/ps
/usr/local/bin/push-sidecar >/tmp/ps/out 2>&1 &
pid=$!
sleep 3
kill -TERM $pid
wait $pid
echo "rc=$?"
cat /tmp/ps/out
echo "tree=$(git -C remote.git ls-tree -r --name-only task | tr "\n" ",")"' 2>&1)
assert_contains "pathspec-like name: the large file is named as skipped" "skipped 1 file(s) over 10 MB: :(glob)z.bin" "$out"
assert_contains "pathspec-like name: only the small file is pushed" "tree=normal.txt," "$out"

# The final path pushes HEAD first, then bounds the rest to 20 s in total. The remote
# hook lets the first push through and blocks the second.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -- bash -c "$ps_setup"'
printf "#!/bin/sh\nif [ -e /tmp/ps/first ]; then sleep 60; fi\ntouch /tmp/ps/first\n" > remote.git/hooks/pre-receive
chmod +x remote.git/hooks/pre-receive
git -C work -c user.name=a -c user.email=a@x commit -q --allow-empty -m "agent own commit"
echo uncommitted > work/b.txt
/usr/local/bin/push-sidecar >/tmp/ps/out 2>&1 &
pid=$!
sleep 3
start=$(date +%s)
kill -TERM $pid
wait $pid
echo "rc=$?"
echo "elapsed=$(($(date +%s) - start))"
cat /tmp/ps/out
echo "subject=$(git -C remote.git log task -1 --format=%s)"' 2>&1)
assert_contains "final budget: HEAD is pushed first" "push-note: HEAD pushed" "$out"
assert_contains "final budget: the agent's own commit reaches the remote" "subject=agent own commit" "$out"
assert_contains "final budget: the second push is cut off" "push-failed: timed out after" "$out"
assert_contains "final budget: exit 1" "rc=1" "$out"
case "$out" in *"elapsed=19"* | *"elapsed=20"* | *"elapsed=21"* | *"elapsed=22"*) pass "final budget: the whole final path ends in about 20 s" ;; *) fail "final budget: the whole final path ends in about 20 s" "$out" ;; esac
# A stuck first push is limited to 10 s, and the commit step then still has time.
# shellcheck disable=SC2016 # expands in the container
out=$(kr -- bash -c "$ps_setup"'
printf "#!/bin/sh\nsleep 60\n" > remote.git/hooks/pre-receive
chmod +x remote.git/hooks/pre-receive
git -C work -c user.name=a -c user.email=a@x commit -q --allow-empty -m "agent own commit"
echo uncommitted > work/b.txt
/usr/local/bin/push-sidecar >/tmp/ps/out 2>&1 &
pid=$!
sleep 3
start=$(date +%s)
kill -TERM $pid
wait $pid
echo "rc=$?"
echo "elapsed=$(($(date +%s) - start))"
cat /tmp/ps/out' 2>&1)
assert_contains "final budget: a stuck HEAD push is reported" "push-note: pushing HEAD failed: timed out after 10s" "$out"
case "$out" in *"elapsed=19"* | *"elapsed=20"* | *"elapsed=21"* | *"elapsed=22"*) pass "final budget: the final path with two stuck pushes ends in about 20 s" ;; *) fail "final budget: the final path with two stuck pushes ends in about 20 s" "$out" ;; esac

# The dispatcher stops the whole container fast. Kelos starts a custom image with the
# command /kelos_entrypoint.sh and no tini, so the dispatcher is PID 1 (mode pid1); the
# image ENTRYPOINT with tini is the other way in (mode tini). A fake agent starts a plain
# child and a child in its own session (setsid), as claude's shell tool can. podman stop
# gives a 30 s grace period; the container must be gone within 5 s, with exit code 143.
fast_stop_run() {
	_type=$1 _fake=$2 _mode=$3 _name=ks-$$-$1-$3
	_bin=/usr/local/bin/claude
	[ "$_type" = codex ] && _bin=/usr/local/bin/codex
	_init=
	[ "$_mode" = tini ] && _init="/usr/bin/tini -g --"
	"$RUNTIME" run -d --pull=never ${PLATFORM:+--platform "$PLATFORM"} --network none --name "$_name" --user 0 \
		-e "KELOS_AGENT_TYPE=$_type" -e HOME=/home/kelos -e CLAUDE_CODE_OAUTH_TOKEN=x \
		--entrypoint sh "$IMAGE" -c "rm -f $_bin; printf '$_fake' > $_bin; chmod 755 $_bin; \
exec setpriv --reuid 61100 --regid 61100 --clear-groups $_init /kelos_entrypoint.sh hi" >/dev/null
}
for mode in pid1 tini; do
	for type in claude-code codex; do
		name=ks-$$-$type-$mode
		fast_stop_run "$type" '#!/bin/sh\nsetsid sleep 600 &\nsleep 600 &\nwait\n' "$mode"
		sleep 5
		# shellcheck disable=SC2016 # expands in the container
		count=$("$RUNTIME" exec "$name" sh -c 'n=0; for f in /proc/[0-9]*/comm; do [ "$(cat $f 2>/dev/null)" = sleep ] && n=$((n + 1)); done; echo $n')
		start=$(date +%s)
		"$RUNTIME" stop -t 30 "$name" >/dev/null 2>&1
		elapsed=$(($(date +%s) - start))
		code=$("$RUNTIME" inspect "$name" --format '{{.State.ExitCode}}')
		"$RUNTIME" rm -f "$name" >/dev/null 2>&1
		if [ "${count:-0}" -ge 2 ]; then pass "$mode $type: the fake agent's two sleeps were running"; else fail "$mode $type: the fake agent's two sleeps were running" "count=$count"; fi
		if [ "$elapsed" -le 5 ]; then pass "$mode $type: podman stop finishes within 5 s ($elapsed s)"; else fail "$mode $type: podman stop finishes within 5 s" "took $elapsed s"; fi
		assert_eq "$mode $type: exit code 143 after SIGTERM" "143" "$code"
	done
done
# The agent's own exit status passes through, and leftovers in another session do not hold the container.
fast_stop_run claude-code '#!/bin/sh\nsetsid sleep 600 >/dev/null 2>&1 </dev/null &\nexit 3\n' pid1
name=ks-$$-claude-code-pid1
start=$(date +%s)
code=$("$RUNTIME" wait "$name" 2>/dev/null)
elapsed=$(($(date +%s) - start))
"$RUNTIME" rm -f "$name" >/dev/null 2>&1
assert_eq "the agent's exit status 3 passes through" "3" "$code"
if [ "$elapsed" -le 10 ]; then pass "the container ends when the agent ends ($elapsed s)"; else fail "the container ends when the agent ends" "took $elapsed s"; fi
# When PID 1 is neither the dispatcher nor tini (a shared PID namespace), the dispatcher
# stops only its own descendants. A same-user sleep started by PID 1 must survive.
name=ks-$$-shared
# shellcheck disable=SC2016 # expands in the container
"$RUNTIME" run -d --pull=never ${PLATFORM:+--platform "$PLATFORM"} --network none --name "$name" --user 0 \
	-e KELOS_AGENT_TYPE=claude-code -e HOME=/home/kelos -e CLAUDE_CODE_OAUTH_TOKEN=x \
	--entrypoint sh "$IMAGE" -c "rm -f /usr/local/bin/claude; printf '#!/bin/sh\nsleep 600 &\nsleep 600 &\nwait\n' > /usr/local/bin/claude; chmod 755 /usr/local/bin/claude; \
setpriv --reuid 61100 --regid 61100 --clear-groups sleep 601 & \
setpriv --reuid 61100 --regid 61100 --clear-groups /kelos_entrypoint.sh hi; wait" >/dev/null
sleep 8
# shellcheck disable=SC2016 # expands in the container
"$RUNTIME" exec "$name" sh -c 'for f in /proc/[0-9]*/comm; do p=${f#/proc/}; p=${p%/comm}; [ "$(cat $f 2>/dev/null)" = kelos_entrypoin ] && echo $p; done | sort -n | head -1 | xargs kill -TERM'
sleep 6
# shellcheck disable=SC2016 # expands in the container
left=$("$RUNTIME" exec "$name" sh -c 'for f in /proc/[0-9]*/cmdline; do tr "\0" " " < $f 2>/dev/null; echo; done | grep -c -E "(^|/)[s]leep 60[01] "')
# shellcheck disable=SC2016 # expands in the container
sibling=$("$RUNTIME" exec "$name" sh -c 'for f in /proc/[0-9]*/cmdline; do tr "\0" " " < $f 2>/dev/null; echo; done | grep -c -E "(^|/)[s]leep 601 "')
"$RUNTIME" rm -f "$name" >/dev/null 2>&1
assert_eq "shared namespace: the agent's own sleeps are stopped, the sibling sleep remains" "1 1" "$left $sibling"
# A shared PID namespace where PID 1 is a sibling container's tini (same user): the dispatcher
# is not PID 1 and tini is not its parent, so it must not signal the sibling's processes.
sib=ks-$$-sibling
name=ks-$$-tinishared
"$RUNTIME" run -d --pull=never ${PLATFORM:+--platform "$PLATFORM"} --network none --name "$sib" --user 61100 \
	--entrypoint /usr/bin/tini "$IMAGE" -g -- sleep 609 >/dev/null
# shellcheck disable=SC2016 # expands in the container
"$RUNTIME" run -d --pull=never ${PLATFORM:+--platform "$PLATFORM"} --network none --name "$name" --pid="container:$sib" --user 0 \
	-e KELOS_AGENT_TYPE=claude-code -e HOME=/home/kelos -e CLAUDE_CODE_OAUTH_TOKEN=x \
	--entrypoint sh "$IMAGE" -c "rm -f /usr/local/bin/claude; printf '#!/bin/sh\nsleep 600 &\nwait\n' > /usr/local/bin/claude; chmod 755 /usr/local/bin/claude; \
exec setpriv --reuid 61100 --regid 61100 --clear-groups /kelos_entrypoint.sh hi" >/dev/null
sleep 8
# shellcheck disable=SC2016 # expands in the container
"$RUNTIME" exec "$name" sh -c 'for f in /proc/[0-9]*/comm; do p=${f#/proc/}; p=${p%/comm}; [ "$(cat $f 2>/dev/null)" = kelos_entrypoin ] && echo $p; done | sort -n | head -1 | xargs kill -TERM'
sleep 6
sib_running=$("$RUNTIME" inspect "$sib" --format '{{.State.Running}}')
agent_code=$("$RUNTIME" inspect "$name" --format '{{.State.ExitCode}}')
"$RUNTIME" rm -f "$name" "$sib" >/dev/null 2>&1
assert_eq "shared namespace under a sibling's tini: the sibling keeps running and the agent exits 143" "true 143" "$sib_running $agent_code"

# SIGINT exits 130, and SIGTERM 143 (above).
fast_stop_run claude-code '#!/bin/sh\nsleep 600 &\nwait\n' pid1
name=ks-$$-claude-code-pid1
sleep 5
"$RUNTIME" kill --signal INT "$name" >/dev/null 2>&1
code=$("$RUNTIME" wait "$name" 2>/dev/null)
"$RUNTIME" rm -f "$name" >/dev/null 2>&1
assert_eq "SIGINT exits 130" "130" "$code"
# The stop timer's file descriptor is not inherited by the agent.
fast_stop_run claude-code '#!/bin/sh\nls -l /proc/$$/fd >&2\nexit 0\n' pid1
name=ks-$$-claude-code-pid1
"$RUNTIME" wait "$name" >/dev/null 2>&1
fds=$("$RUNTIME" logs "$name" 2>&1)
"$RUNTIME" rm -f "$name" >/dev/null 2>&1
assert_absent "the agent does not inherit the stop timer descriptor" "$fds" "total" "kelos-stop"
# The traps are set before the guards run.
# shellcheck disable=SC2016 # expands in the container
assert_eq "the stop traps come before the guards" "ok" "$(kr -- sh -c '
	t=$(grep -n "^setup_stop\$" /kelos_entrypoint.sh | head -1 | cut -d: -f1)
	g=$(grep -n "^kelos_preflight\$" /kelos_entrypoint.sh | head -1 | cut -d: -f1)
	[ -n "$t" ] && [ -n "$g" ] && [ "$t" -lt "$g" ] && echo ok')"
assert_contains "the dispatcher header explains why it supervises" "Kelos starts an agent container with the command" "$(kr -- head -n 120 /kelos_entrypoint.sh)"

# MCP gateway. A Task may mount a Secret with the keys url and token at
# /etc/agentainer/mcp. Each test writes the files as root in its throwaway
# container, then runs the dispatcher, the wrapper or the helper as UID 61100.
# Values travel base64-encoded so that quotes and newlines reach the files byte
# for byte. MCP_U and MCP_T name the url and token contents; an unset variable
# means no file. The URL and token are made up.
b64() { printf '%s' "$1" | base64 | tr -d '\n'; }
b64nl() { printf '%s\n' "$1" | base64 | tr -d '\n'; }
mcp_url=https://gw.example.test/mcp
mcp_token=t0k-abcdefghijklm
# shellcheck disable=SC2016 # expands in the container
mcp_write='mkdir -p /etc/agentainer/mcp
if [ -n "${MCP_U+x}" ]; then printf %s "$MCP_U" | base64 -d >/etc/agentainer/mcp/url; fi
if [ -n "${MCP_T+x}" ]; then printf %s "$MCP_T" | base64 -d >/etc/agentainer/mcp/token; fi
chmod 0755 /etc/agentainer/mcp
chmod 0644 /etc/agentainer/mcp/* 2>/dev/null
as_kelos() { setpriv --reuid 61100 --regid 61100 --clear-groups "$@"; }
'
# mcp_kr [runtime options...] -- SCRIPT: writes the files, then runs SCRIPT.
mcp_kr() {
	_script=""
	for _a; do _script=$_a; done
	_n=$#
	_i=0
	for _a; do
		_i=$((_i + 1))
		shift
		[ "$_i" -lt "$_n" ] && set -- "$@" "$_a"
	done
	kr --user 0 -e HOME=/home/kelos -e CLAUDE_CODE_OAUTH_TOKEN=x "$@" sh -c "$mcp_write$_script"
}
# mcp_setup_rc AGENT [runtime options...]: exit code of a setup-only start.
mcp_setup_rc() {
	_agent=$1
	shift
	mcp_kr -e KELOS_AGENT_TYPE="$_agent" -e KELOS_SESSION_SETUP_ONLY=1 "$@" -- 'as_kelos /kelos_entrypoint.sh >/dev/null 2>&1; echo $?'
}

# The header helper prints the bearer header, also for a token file that ends in
# one newline, and fails with no output when the token file is missing.
assert_eq "mcp-headers is mode 755" "755" "$(kr -- stat -c %a /usr/local/lib/kelos/mcp-headers 2>&1)"
assert_eq "mcp-headers prints the bearer header" '{"Authorization":"Bearer t0k-abcdefghijklm"}' \
	"$(mcp_kr -e "MCP_U=$(b64 "$mcp_url")" -e "MCP_T=$(b64 "$mcp_token")" -- 'as_kelos /usr/local/lib/kelos/mcp-headers' 2>&1)"
assert_eq "mcp-headers drops one trailing newline" '{"Authorization":"Bearer t0k-abcdefghijklm"}' \
	"$(mcp_kr -e "MCP_U=$(b64 "$mcp_url")" -e "MCP_T=$(b64nl "$mcp_token")" -- 'as_kelos /usr/local/lib/kelos/mcp-headers' 2>&1)"
assert_eq "mcp-headers without a token fails with no output" "rc=1" \
	"$(mcp_kr -e "MCP_U=$(b64 "$mcp_url")" -- 'as_kelos /usr/local/lib/kelos/mcp-headers 2>/dev/null; echo "rc=$?"')"

# Claude: a stub in place of the real binary prints its arguments. With both files
# the wrapper adds --mcp-config with a file that names one server and the helper,
# and the token is not in that file. Without the files, or with an empty
# directory (a missing optional Secret), no --mcp-config is passed.
# shellcheck disable=SC2016 # expands in the stub
claude_stub='#!/bin/sh
for a; do printf "arg=%s\n" "$a"; done
'
# shellcheck disable=SC2016 # expands in the container
claude_mcp_run='printf "%s" "$STUB" >/usr/local/bin/claude && chmod 755 /usr/local/bin/claude
cd /tmp && as_kelos /usr/local/lib/kelos/bin/claude -p hi
f=/home/kelos/.claude/mcp-gateway.json
if [ -f "$f" ]; then
	jq -e --arg u "$URL" '"'"'(.mcpServers | keys) == ["gateway"] and .mcpServers.gateway == {"type": "http", "url": $u, "headersHelper": "/usr/local/lib/kelos/mcp-headers"}'"'"' "$f" >/dev/null && echo config-ok
	grep -qF "$TOKEN" "$f" && echo token-in-config
fi
true'
out=$(mcp_kr -e "STUB=$claude_stub" -e "URL=$mcp_url" -e "TOKEN=$mcp_token" -e "MCP_U=$(b64 "$mcp_url")" -e "MCP_T=$(b64 "$mcp_token")" -- "$claude_mcp_run" 2>&1)
assert_contains "claude gets --mcp-config with the gateway file" "arg=--mcp-config
arg=/home/kelos/.claude/mcp-gateway.json" "$out"
assert_contains "the gateway file has one http server with the helper" "config-ok" "$out"
assert_absent "the token is not in the gateway file" "$out" "config-ok" "token-in-config"
# shellcheck disable=SC2016 # expands in the container
out=$(kr --user 0 -e HOME=/home/kelos -e CLAUDE_CODE_OAUTH_TOKEN=x -e "STUB=$claude_stub" -- sh -c '
	printf "%s" "$STUB" >/usr/local/bin/claude && chmod 755 /usr/local/bin/claude
	rm -rf /etc/agentainer/mcp
	cd /tmp && setpriv --reuid 61100 --regid 61100 --clear-groups /usr/local/lib/kelos/bin/claude -p hi' 2>&1)
assert_absent "claude without MCP files gets no --mcp-config" "$out" "arg=--strict-mcp-config" "arg=--mcp-config"
out=$(mcp_kr -e "STUB=$claude_stub" -e "URL=$mcp_url" -e "TOKEN=$mcp_token" -- "$claude_mcp_run" 2>&1)
assert_absent "claude with an empty MCP directory gets no --mcp-config" "$out" "arg=--strict-mcp-config" "arg=--mcp-config" "config-ok"
for agent in claude-code codex; do
	assert_eq "$agent: an empty MCP directory starts" "0" "$(mcp_setup_rc "$agent")"
done

# Codex: the real binary reads the block that the entrypoint appends last. The
# setting written earlier stays at top level, the agent's shell loses every
# AGENTAINER_MCP_* variable, and the token is not in config.toml.
# shellcheck disable=SC2016 # expands in the container
out=$(mcp_kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -e 'CODEX_AUTH_JSON={"new":1}' -e "URL=$mcp_url" -e "TOKEN=$mcp_token" \
	-e "MCP_U=$(b64 "$mcp_url")" -e "MCP_T=$(b64 "$mcp_token")" -- '
	as_kelos /kelos_entrypoint.sh >/dev/null 2>&1 || echo "setup failed"
	c=/home/kelos/.codex/config.toml
	as_kelos env CODEX_HOME=/home/kelos/.codex codex mcp get gateway --json 2>/dev/null |
		jq -e --arg u "$URL" '"'"'.transport.url == $u and .transport.bearer_token_env_var == "AGENTAINER_MCP_TOKEN"'"'"' >/dev/null && echo get-ok
	awk '"'"'/^\[/ { t = 1 } $0 == "cli_auth_credentials_store = \"file\"" && !t { print "auth-top-level" }'"'"' "$c"
	grep -A1 -xF "[shell_environment_policy.filters]" "$c" | grep -qxF "\"AGENTAINER_MCP_*\" = \"exclude\"" && echo filter-ok
	grep -qF "$TOKEN" "$c" && echo token-in-config
	echo done' 2>&1)
assert_contains "codex mcp get shows the gateway URL and bearer variable" "get-ok" "$out"
assert_contains "cli_auth_credentials_store stays at top level" "auth-top-level" "$out"
assert_contains "the shell policy excludes AGENTAINER_MCP_*" "filter-ok" "$out"
assert_absent "the token is not in config.toml" "$out" "done" "token-in-config" "setup failed"
# shellcheck disable=SC2016 # expands in the container
out=$(mcp_kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -- '
	as_kelos /kelos_entrypoint.sh >/dev/null 2>&1 && echo "mcp_servers=$(grep -c "mcp_servers" /home/kelos/.codex/config.toml)"' 2>&1)
assert_eq "codex without MCP files has no mcp_servers table" "mcp_servers=0" "$out"
# A real start hands the token to codex in its environment only. A stub codex
# prints what it receives.
# shellcheck disable=SC2016 # expands in the stub
codex_tok_stub='#!/bin/sh
echo "codex-token=${AGENTAINER_MCP_TOKEN:-unset}" >&2
exit 0
'
# shellcheck disable=SC2016 # expands in the container
out=$(mcp_kr -e KELOS_AGENT_TYPE=codex -e "STUB=$codex_tok_stub" -e "MCP_U=$(b64 "$mcp_url")" -e "MCP_T=$(b64nl "$mcp_token")" -- '
	printf "%s" "$STUB" >/usr/local/bin/codex && chmod 755 /usr/local/bin/codex
	as_kelos /kelos_entrypoint.sh hi; echo "rc=$?"' 2>&1)
assert_contains "codex receives the token in AGENTAINER_MCP_TOKEN" "codex-token=t0k-abcdefghijklm
" "$out"
assert_contains "the codex start with MCP exits 0" "rc=0" "$out"

# Exactly one of the two files is refused, for both CLIs.
for agent in claude-code codex; do
	assert_eq "$agent: only the url file is refused" "78" "$(mcp_setup_rc "$agent" -e "MCP_U=$(b64 "$mcp_url")")"
	assert_eq "$agent: only the token file is refused" "78" "$(mcp_setup_rc "$agent" -e "MCP_T=$(b64 "$mcp_token")")"
	assert_eq "$agent: a url and token with one trailing newline each start" "0" \
		"$(mcp_setup_rc "$agent" -e "MCP_U=$(b64nl "$mcp_url")" -e "MCP_T=$(b64nl "$mcp_token")")"
done

# A URL that is not https, or that holds a quote, backslash, space, newline or
# query, is refused and the url file is named. So is one over 512 bytes.
long_url=https://gw.example.test/$(head -c 500 /dev/zero | tr '\0' a)
mcp_url_case() {
	for agent in claude-code codex; do
		out=$(mcp_kr -e KELOS_AGENT_TYPE="$agent" -e KELOS_SESSION_SETUP_ONLY=1 -e "MCP_U=$(b64 "$2")" -e "MCP_T=$(b64 "$mcp_token")" -- \
			'as_kelos /kelos_entrypoint.sh; echo "rc=$?"' 2>&1)
		assert_contains "$agent: url $1 is refused" "rc=78" "$out"
		assert_contains "$agent: url $1 refusal names the file" "/etc/agentainer/mcp/url" "$out"
	done
}
mcp_url_case "http" "http://gw.example.test/mcp"
mcp_url_case "with a quote" 'https://gw.example.test/m"cp'
mcp_url_case "with a backslash" 'https://gw.example.test/m\cp'
mcp_url_case "with a space" 'https://gw.example.test/m cp'
mcp_url_case "with a newline" "$(printf 'https://gw.example.test/mcp\nhttps://other.example.test/')"
mcp_url_case "with a query" 'https://gw.example.test/mcp?x=1'
mcp_url_case "over 512 bytes" "$long_url"

# A token that is empty, under 16 characters, holds a quote, backslash or space,
# or is over 4096 bytes is refused. The refusal names the file, never the value.
# 16 and 4096 characters are accepted.
mcp_token_case() {
	assert_eq "token $1 is refused" "78" "$(mcp_setup_rc claude-code -e "MCP_U=$(b64 "$mcp_url")" -e "MCP_T=$(b64 "$2")")"
}
mcp_token_case "empty" ""
mcp_token_case "of 15 characters" "abcdefghijklmno"
mcp_token_case "with a quote" 'abcdefghijklmnop"q'
mcp_token_case "with a backslash" 'abcdefghijklmnop\q'
mcp_token_case "with a space" 'abcdefghijklmnop q'
mcp_token_case "over 4096 bytes" "$(head -c 4097 /dev/zero | tr '\0' a)"
assert_eq "a token of 16 characters is accepted" "0" "$(mcp_setup_rc codex -e "MCP_U=$(b64 "$mcp_url")" -e "MCP_T=$(b64 abcdefghijklmnop)")"
assert_eq "a token of 4096 characters is accepted" "0" "$(mcp_setup_rc codex -e "MCP_U=$(b64 "$mcp_url")" -e "MCP_T=$(b64 "$(head -c 4096 /dev/zero | tr '\0' a)")")"
out=$(mcp_kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -e "MCP_U=$(b64 "$mcp_url")" -e "MCP_T=$(b64 short-token-val)" -- \
	'as_kelos /kelos_entrypoint.sh; echo "rc=$?"' 2>&1)
assert_contains "a short token refusal names the file" "/etc/agentainer/mcp/token" "$out"
assert_absent "a short token refusal does not print the value" "$out" "rc=78" "short-token-val"

# The token must come from the file, never the pod environment.
for agent in claude-code codex; do
	out=$(kr -e KELOS_AGENT_TYPE="$agent" -e KELOS_SESSION_SETUP_ONLY=1 -e CLAUDE_CODE_OAUTH_TOKEN=x -e AGENTAINER_MCP_TOKEN=abcdefghijklmnop -- /kelos_entrypoint.sh 2>&1)
	rc=$?
	assert_eq "$agent: AGENTAINER_MCP_TOKEN in the environment is refused" "78" "$rc"
	assert_contains "$agent: the refusal names AGENTAINER_MCP_TOKEN" "AGENTAINER_MCP_TOKEN" "$out"
done

finish
