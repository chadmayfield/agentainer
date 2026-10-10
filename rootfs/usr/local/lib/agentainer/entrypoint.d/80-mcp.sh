# Step 8: sync MCP servers when ~/.agentainer/mcp.json changed (spec 8).
f="$HOME/.agentainer/mcp.json"
h="$HOME/.agentainer/.mcp-synced.sha256"
if [ ! -f "$f" ]; then
	# A deleted file after an earlier sync: one sync with no servers removes the managed ones.
	[ -f "$h" ] || return 0
	agentainer-mcp sync
	rm -f "$h"
	return 0
fi
new=$(sha256sum "$f" | cut -d' ' -f1)
[ -f "$h" ] && [ "$(cat "$h")" = "$new" ] && return 0
agentainer-mcp sync
printf '%s\n' "$new" >"$h"
