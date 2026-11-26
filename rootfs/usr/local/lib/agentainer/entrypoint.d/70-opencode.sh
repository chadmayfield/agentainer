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
if [ ! -e "$HOME/.config/opencode/service.json" ] && [ ! -L "$HOME/.config/opencode/service.json" ]; then
	# OpenCode 2.4.2 sets the stderr it inherits to non-blocking and leaves it so. That
	# file description is shared with the container command, and ansible then refuses to
	# run ("Ansible requires blocking IO"). Capturing stderr keeps it off the shared one.
	if ! err=$(opencode service set disabled true 2>&1 >/dev/null 9>&-); then
		warn "could not disable the OpenCode service: $err"
		return 1
	fi
fi
touch "$marker"
