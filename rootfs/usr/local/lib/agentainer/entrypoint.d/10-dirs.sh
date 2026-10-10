# Step 1: check that home is writable, then create the agentainer directories.
if [ ! -w "$HOME" ]; then
	log "$HOME is not writable by uid $(id -u); give the home volume to uid $(id -u) (for example: chown -R $(id -u):$(id -g) on the volume)"
	return 1
fi
mkdir -p "$HOME/.agentainer" "$HOME/.config" "$HOME/.local/share"
