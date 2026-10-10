# Step 8: sync MCP servers when ~/.agentainer/mcp.json changed (spec 8).
f="$HOME/.agentainer/mcp.json"
[ -f "$f" ] || return 0
h="$HOME/.agentainer/.mcp-synced.sha256"
new=$(sha256sum "$f" | cut -d' ' -f1)
[ -f "$h" ] && [ "$(cat "$h")" = "$new" ] && return 0
agentainer-mcp sync
printf '%s\n' "$new" >"$h"
