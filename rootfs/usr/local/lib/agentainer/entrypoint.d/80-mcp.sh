# Step 8: sync MCP servers when ~/.agentainer/mcp.json changed (spec 8).
# Containers sharing a home volume take turns: each holds a lock while it compares the
# hash, syncs and records the new hash. The lock is released when this step's subshell exits,
# and agentainer-mcp gets fd 9 closed, so no agent process it starts can keep the lock.
exec 9>"$HOME/.agentainer/.mcp-sync.lock"
if ! flock -w 120 9; then
	warn "another container held the MCP sync lock for 120 seconds; not syncing now"
	return 1
fi
f="$HOME/.agentainer/mcp.json"
h="$HOME/.agentainer/.mcp-synced.sha256"
if [ ! -f "$f" ]; then
	# A deleted file after an earlier sync: one sync with no servers removes the managed ones.
	[ -f "$h" ] || return 0
	agentainer-mcp sync 9>&-
	rm -f "$h"
	return 0
fi
new=$(sha256sum "$f" | cut -d' ' -f1)
[ -f "$h" ] && [ "$(cat "$h")" = "$new" ] && return 0
agentainer-mcp sync 9>&-
printf '%s\n' "$new" >"$h"
