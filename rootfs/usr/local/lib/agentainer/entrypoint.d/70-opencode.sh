# Step 7: make OpenCode use a private server per command, once. The setting is stored in
# ~/.config/opencode/service.json, so an existing file is the user's (or an earlier
# start's) and is left alone, even when the marker in ~/.agentainer is gone.
marker="$HOME/.agentainer/.opencode-service-disabled"
[ -f "$marker" ] && return 0
# OpenCode writes service.json through a fixed temp name, service.json.tmp, so containers
# sharing a home volume take turns.
exec 9>"$HOME/.agentainer/.home-config.lock"
if ! flock -w 60 9; then
	warn "another container held the home config lock for 60 seconds; not configuring OpenCode"
	return 1
fi
[ -f "$marker" ] && return 0
if [ ! -e "$HOME/.config/opencode/service.json" ]; then
	opencode service set disabled true >/dev/null 9>&-
fi
touch "$marker"
