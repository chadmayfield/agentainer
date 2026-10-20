# Step 1: check that home is writable, then create the agentainer directories.
if [ ! -w "$HOME" ]; then
	log "$HOME is not writable by uid $(id -u); give the home volume to uid $(id -u) (for example: chown -R $(id -u):$(id -g) on the volume)"
	return 1
fi
# A directory left by another uid (for example a root-owned copy) would make later steps
# fail with a bare "Permission denied", so name it and its owner here.
for d in "$HOME/.agentainer" "$HOME/.config" "$HOME/.local/share"; do
	mkdir -p "$d" 2>/dev/null || true
	if [ -d "$d" ] && [ -w "$d" ]; then continue; fi
	# Report the deepest path that exists: the directory itself or the parent that blocks it.
	p=$d
	while [ ! -e "$p" ] && [ ! -L "$p" ]; do p=$(dirname "$p"); done
	if [ -d "$p" ]; then
		log "$p is owned by uid $(stat -c %u "$p") and not writable by uid $(id -u); give it to uid $(id -u) (for example: chown -R $(id -u):$(id -g) $p)"
	else
		log "$p is not a directory; move it aside so agentainer can create $d"
	fi
	return 1
done
