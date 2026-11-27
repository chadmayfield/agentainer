# Step 7: make OpenCode use a private server per command, once. The setting is stored in
# ~/.config/opencode/service.json ($XDG_CONFIG_HOME/opencode when that is set), so an
# existing file is the user's (or an earlier start's) and is left alone, even when the
# marker in ~/.agentainer is gone.
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
service=$(home_path .config/opencode/service.json)
if [ ! -e "$service" ] && [ ! -L "$service" ]; then
	# OpenCode sets the stdout and stderr it inherits to non-blocking and leaves
	# them so. Those file descriptions are shared with the container command, and ansible
	# then refuses to run ("Ansible requires blocking IO"). OpenCode gets none of the
	# container's descriptors: stdin and stdout are /dev/null, stderr is captured.
	if ! err=$(opencode service set disabled true 2>&1 >/dev/null </dev/null 9>&-); then
		warn "could not disable the OpenCode service: $err"
		return 1
	fi
fi
touch "$marker"
