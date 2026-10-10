# Step 8: sync MCP servers when ~/.agentbox/mcp.json changed (spec 8).
f="$HOME/.agentbox/mcp.json"
[ -f "$f" ] || return 0
h="$HOME/.agentbox/.mcp-synced.sha256"
new=$(sha256sum "$f" | cut -d' ' -f1)
[ -f "$h" ] && [ "$(cat "$h")" = "$new" ] && return 0
agentbox-mcp sync
printf '%s\n' "$new" >"$h"
