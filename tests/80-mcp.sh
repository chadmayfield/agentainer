#!/bin/sh
# shellcheck disable=SC2086 # H holds "-v vol:/home/agent" on purpose
# shellcheck disable=SC2016 # single-quoted scripts expand in the container
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"
VOL="agentbox-test-home-$$"
"$RUNTIME" volume create "$VOL" >/dev/null
trap '"$RUNTIME" volume rm -f "$VOL" >/dev/null' EXIT
H="-v $VOL:/home/agent"

run_in $H --entrypoint sh -- -c 'mkdir -p ~/.agentbox && printf "%s" "{\"mcpServers\":{\"everything\":{\"command\":\"npx\",\"args\":[\"-y\",\"@modelcontextprotocol/server-everything\"]},\"web\":{\"url\":\"https://mcp.example.com/mcp\",\"headers\":{\"Authorization\":\"Bearer \${WEB_TOKEN}\"}}}}" > ~/.agentbox/mcp.json' >/dev/null
out=$(run_in $H --network none -- agentbox-mcp list 2>/dev/null)
for a in claude codex opencode agy; do
	assert_contains "$a has the managed servers" "$a: everything, web" "$out"
done
assert_contains "claude sees it" "everything" "$(run_in $H --network none -- claude mcp list 2>/dev/null)"
assert_contains "codex sees it" "everything" "$(run_in $H --network none -- codex mcp list 2>/dev/null)"
# "opencode mcp list" shows servers with their live status and lists none offline;
# the resolved config is what OpenCode loads.
assert_contains "opencode sees it" '"everything"' "$(run_in $H --network none -- opencode debug config 2>/dev/null)"
assert_contains "agy sees it" "everything" "$(run_in $H --network none -- agy mcp list 2>/dev/null)"
assert_contains "codex uses the bearer env var" 'bearer_token_env_var = "WEB_TOKEN"' "$(run_in $H -- cat /home/agent/.codex/config.toml 2>/dev/null)"

# Removing a server from mcp.json removes it everywhere on the next start.
run_in $H --entrypoint sh -- -c 'printf "%s" "{\"mcpServers\":{\"web\":{\"url\":\"https://mcp.example.com/mcp\"}}}" > ~/.agentbox/mcp.json' >/dev/null
out=$(run_in $H --network none -- sh -c 'claude mcp list; codex mcp list; opencode debug config; agy mcp list' 2>/dev/null)
case "$out" in
*everything*) fail "removed server is gone from every agent" "$out" ;;
*) pass "removed server is gone from every agent" ;;
esac

# The unit tests again, on the image's Python, where the real TOML parser checks Codex output.
repo=$(cd "$(dirname "$0")/.." && pwd)
assert_contains "MCP unit tests pass on the image's Python (tomllib)" "OK" \
	"$("$RUNTIME" run --rm --network none -v "$repo:/src:ro" -w /src --entrypoint python3 "$IMAGE" -m unittest tests.unit.test_mcp_sync 2>&1 | grep -E '^(OK|FAILED)')"

# A user's own Codex settings after agentbox's block survive a re-sync, and Codex still loads the file.
run_in $H --entrypoint sh -- -c 'printf "\n[profiles.mine] # mine\nmodel = \"keepme\"\n" >> ~/.codex/config.toml' >/dev/null
run_in $H --entrypoint sh -- -c 'printf "%s" "{\"mcpServers\":{\"web2\":{\"url\":\"https://mcp.example.com/mcp\"}}}" > ~/.agentbox/mcp.json' >/dev/null
assert_contains "user Codex settings survive" 'model = "keepme"' "$(run_in $H -- cat /home/agent/.codex/config.toml 2>/dev/null)"
assert_eq "Codex still loads its config" "ok" \
	"$(run_in $H --network none -- sh -c 'codex --strict-config doctor --json 2>/dev/null' | python3 -c 'import sys,json; print(json.load(sys.stdin)["checks"]["config.load"]["status"])' 2>&1)"

# Review focus 4: a malformed file keeps the container up.
assert_contains "malformed file keeps the container up" "ok" \
	"$(run_in $H --entrypoint sh -- -c 'echo "{bad" > ~/.agentbox/mcp.json; agentbox-entrypoint echo ok 2>/dev/null')"

finish
