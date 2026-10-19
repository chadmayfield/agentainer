# Step 3: wire ~/.agentainer/AGENTS.md into each agent's user-level file.
# Anything the user already has at a target path is left alone, with a warning.
canon="$HOME/.agentainer/AGENTS.md"
for target in "$HOME/.codex/AGENTS.md" "$HOME/.gemini/AGENTS.md" "$HOME/.config/opencode/AGENTS.md"; do
	if [ -L "$target" ]; then
		if [ ! -e "$target" ]; then
			warn "$target points to a missing file; that agent gets no AGENTS.md"
		fi
		continue
	elif [ -e "$target" ]; then
		warn "$target exists and is not a symlink; leaving it and not linking it to $canon"
	elif ! { mkdir -p "$(dirname "$target")" 2>/dev/null && ln -s "$canon" "$target" 2>/dev/null; }; then
		warn "could not link $target (something else is in the way); skipping"
	fi
done
# agents-default.sha256 lists every image default this home has seen, one hash per line.
# Only a default not seen before counts as a change, so two images that share a home
# volume do not report each other's default on every start.
new=$(sha256sum /etc/agentainer/AGENTS.md | cut -d' ' -f1)
f="$HOME/.agentainer/agents-default.sha256"
if [ -f "$f" ] && ! grep -qxF "$new" "$f"; then
	mine=""
	if [ -f "$canon" ] && [ ! -L "$canon" ]; then mine=$(sha256sum "$canon" | cut -d' ' -f1); fi
	if [ "$mine" = "$new" ]; then
		:
	elif [ -n "$mine" ] && grep -qxF "$mine" "$f"; then
		# The file still matches an earlier image default, so the user never edited it.
		# A unique temp file and a lock keep containers that share the home volume from
		# writing it at the same time; the file keeps its mode.
		tmp=$(mktemp "$HOME/.agentainer/.AGENTS.md.XXXXXX")
		cp /etc/agentainer/AGENTS.md "$tmp"
		chmod "$(stat -c %a "$canon")" "$tmp"
		(
			flock -w 30 9 || exit 0
			if [ "$(sha256sum "$canon" | cut -d' ' -f1)" = "$mine" ]; then mv -f "$tmp" "$canon"; fi
		) 9>"$HOME/.agentainer/.agents-md.lock"
		rm -f "$tmp"
		if [ "$(sha256sum "$canon" | cut -d' ' -f1)" = "$new" ]; then
			log "the image's default AGENTS.md changed; you had not edited ~/.agentainer/AGENTS.md, so agentainer replaced it with the new default"
		else
			log "the image's default AGENTS.md changed; run 'agentainer-agents diff' to compare"
		fi
	else
		log "the image's default AGENTS.md changed; run 'agentainer-agents diff' to compare"
	fi
fi
if ! grep -qxF "$new" "$f" 2>/dev/null; then printf '%s\n' "$new" >>"$f"; fi
