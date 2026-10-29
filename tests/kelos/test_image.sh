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

# Codex: auth.json is seeded only when missing.
# shellcheck disable=SC2016 # expands in the container
assert_eq "codex keeps an existing auth.json" "OLD" "$(kr -e KELOS_AGENT_TYPE=codex -e KELOS_SESSION_SETUP_ONLY=1 -e 'CODEX_AUTH_JSON={"new":1}' -- sh -c '
	mkdir -p ~/.codex && printf OLD > ~/.codex/auth.json
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

finish
