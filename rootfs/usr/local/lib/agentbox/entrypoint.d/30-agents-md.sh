# Step 3: wire ~/.agentbox/AGENTS.md into each agent's user-level file (spec 7).
# Anything the user already has at a target path is left alone, with a warning.
canon="$HOME/.agentbox/AGENTS.md"
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
new=$(sha256sum /etc/agentbox/AGENTS.md | cut -d' ' -f1)
f="$HOME/.agentbox/agents-default.sha256"
if [ -f "$f" ] && [ "$(cat "$f")" != "$new" ]; then
	log "the image's default AGENTS.md changed; run 'agentbox-agents diff' to compare"
fi
printf '%s\n' "$new" >"$f"
