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
start=$SECONDS
kill -TERM $pid
wait $pid
echo "rc=$?"
echo "elapsed=$((SECONDS - start))"
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
start=$SECONDS
kill -TERM $pid
wait $pid
echo "rc=$?"
echo "elapsed=$((SECONDS - start))"
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
start=$SECONDS
kill -TERM $pid
wait $pid
echo "rc=$?"
echo "elapsed=$((SECONDS - start))"
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
start=$SECONDS
kill -TERM $pid
wait $pid
echo "rc=$?"
echo "elapsed=$((SECONDS - start))"
cat /tmp/ps/out' 2>&1)
assert_contains "final budget: a stuck HEAD push is reported" "push-note: pushing HEAD failed: timed out after 10s" "$out"
case "$out" in *"elapsed=19"* | *"elapsed=20"* | *"elapsed=21"* | *"elapsed=22"*) pass "final budget: the final path with two stuck pushes ends in about 20 s" ;; *) fail "final budget: the final path with two stuck pushes ends in about 20 s" "$out" ;; esac

finish
