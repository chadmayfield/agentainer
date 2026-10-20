#!/bin/sh
# shellcheck disable=SC2016 # single-quoted scripts expand in the container
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"

assert_eq "claude wrapper exits 2 without a key" "rc=2" "$(run_in -- sh -c 'openrouter-claude --version >/dev/null 2>&1; echo rc=$?')"
assert_eq "codex wrapper exits 2 without a key" "rc=2" "$(run_in -- sh -c 'openrouter-codex --version >/dev/null 2>&1; echo rc=$?')"

out=$(run_in -e OPENROUTER_API_KEY=sk-or-test -e ANTHROPIC_API_KEY=sk-ant-real --entrypoint sh -- -c '
	mkdir -p /tmp/stub && printf "#!/bin/sh\nenv\n" > /tmp/stub/claude && chmod +x /tmp/stub/claude
	PATH=/tmp/stub:$PATH openrouter-claude')
assert_contains "base URL set" "ANTHROPIC_BASE_URL=https://openrouter.ai/api" "$out"
assert_contains "auth token is the OpenRouter key" "ANTHROPIC_AUTH_TOKEN=sk-or-test" "$out"
assert_eq "API key blanked even when one is set" "ANTHROPIC_API_KEY=" "$(printf '%s\n' "$out" | grep '^ANTHROPIC_API_KEY=')"

out=$(run_in -e OPENROUTER_API_KEY=sk-or-test --entrypoint sh -- -c '
	mkdir -p /tmp/stub && printf "#!/bin/sh\nprintf \"%%s\\\\n\" \"\$@\"\n" > /tmp/stub/codex && chmod +x /tmp/stub/codex
	PATH=/tmp/stub:$PATH openrouter-codex exec "two words"')
assert_contains "codex gets the openrouter provider" 'model_provider="openrouter"' "$out"
assert_contains "codex base URL" "https://openrouter.ai/api/v1" "$out"
assert_contains "codex default model is an OpenRouter id" 'model="~openai/gpt-sol-latest"' "$out"
assert_eq "user args come last and intact" "exec|two words" "$(printf '%s\n' "$out" | tail -2 | paste -sd '|' -)"
assert_absent "codex argv has no key" "$out" 'model_provider="openrouter"' sk-or-test

# End to end against a local fake endpoint: the key reaches the Authorization header.
hdr=$(run_in --network none -e OPENROUTER_API_KEY=sk-or-e2e --entrypoint sh -- -c '
	cat > /tmp/srv.py <<"EOF"
import http.server
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        open("/tmp/auth.txt", "a").write(str(self.headers.get("Authorization")) + "\n")
        self.send_response(500); self.end_headers()
    def log_message(self, *a):
        pass
srv = http.server.HTTPServer(("127.0.0.1", 18080), H)
open("/tmp/ready", "w").close()
srv.serve_forever()
EOF
	# The server creates /tmp/ready after it binds and listens, so a request sent after
	# that waits in the listen queue instead of being refused.
	python3 /tmp/srv.py &
	i=0
	until [ -e /tmp/ready ] || [ "$i" -ge 100 ]; do
		sleep 0.1
		i=$((i + 1))
	done
	timeout 20 openrouter-codex -c "model_providers.openrouter.base_url=\"http://127.0.0.1:18080/v1\"" \
		-c "model_providers.openrouter.request_max_retries=0" exec --skip-git-repo-check "hi" </dev/null >/dev/null 2>&1
	sort -u /tmp/auth.txt 2>/dev/null')
assert_contains "codex sends the OpenRouter key as a Bearer token" "Bearer sk-or-e2e" "$hdr"

doctor=$(run_in --network none -e OPENROUTER_API_KEY=sk-or-test -- sh -c 'openrouter-codex doctor --json 2>/dev/null')
assert_eq "real codex accepts the provider overrides" "ok" \
	"$(printf '%s' "$doctor" | python3 -c 'import sys,json; print(json.load(sys.stdin)["checks"]["config.load"]["status"])' 2>&1)"
assert_absent "codex doctor output has no key" "$doctor" '"config.load"' sk-or-test

# openrouter-claude turns on Claude Code's gateway model picker unless the user set the
# variable.
orstub='mkdir -p /tmp/s && printf "#!/bin/sh\nenv\n" >/tmp/s/claude && chmod +x /tmp/s/claude'
assert_contains "openrouter-claude enables gateway model discovery" "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1" \
	"$(run_in -e OPENROUTER_API_KEY=sk-or-test --entrypoint sh -- -c "$orstub"'; PATH=/tmp/s:$PATH openrouter-claude')"
assert_contains "openrouter-claude keeps the user's discovery setting" "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=0" \
	"$(run_in -e OPENROUTER_API_KEY=sk-or-test -e CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=0 --entrypoint sh -- -c "$orstub"'; PATH=/tmp/s:$PATH openrouter-claude')"

finish
