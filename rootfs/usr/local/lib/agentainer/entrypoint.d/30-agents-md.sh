# Step 3: wire ~/.agentainer/AGENTS.md into each agent's user-level file.
# Anything the user already has at a target path is left alone, with a warning.
# Seeding and recording the default share one lock. A second image must see both the
# complete canonical file and the version that supplied it before it can compare.
exec 9>"$HOME/.agentainer/.agents-md.lock"
if ! flock -w 30 9; then
	warn "another container held the AGENTS.md lock for 30 seconds; not checking the default now"
	return 0
fi
canon="$HOME/.agentainer/AGENTS.md"
if [ -f /etc/agentainer/seed/AGENTS.md ]; then
	seed_file /etc/agentainer/seed/AGENTS.md "$canon" 2>/dev/null ||
		warn "could not seed $canon (something else is in the way); skipping"
fi
seed_file /etc/agentainer/AGENTS.md "$canon" 2>/dev/null ||
	warn "could not seed $canon (something else is in the way); skipping"
for target in "$HOME/.codex/AGENTS.md" "$HOME/.gemini/AGENTS.md" "$HOME/.config/opencode/AGENTS.md"; do
	if [ -L "$target" ]; then
		if [ ! -e "$target" ]; then
			warn "$target points to a missing file; that agent gets no AGENTS.md"
		fi
		continue
	elif [ -e "$target" ]; then
		warn "$target exists and is not a symlink; leaving it and not linking it to $canon"
	elif ! { mkdir -p "$(dirname "$target")" 2>/dev/null && ln -s "$canon" "$target" 2>/dev/null; }; then
		# Another container on the same home volume may have made the same link first.
		if [ "$(readlink "$target" 2>/dev/null)" != "$canon" ]; then
			warn "could not link $target (something else is in the way); skipping"
		fi
	fi
done

# agents-default.sha256 lists every image default this home has seen, one per line as
# "<sha256> <image version>". Lines with only a hash come from images that did not record
# a version; their version counts as unknown, older than any release.
# Compare SemVer against every recorded version for the current content. Prereleases
# may advance prerelease defaults, but never replace a stable release's default.

new=$(sha256sum /etc/agentainer/AGENTS.md | cut -d' ' -f1)
ver=${AGENTAINER_IMAGE_VERSION:-}
f="$HOME/.agentainer/agents-default.sha256"
known=0
if [ -f "$f" ] && awk -v h="$new" '$1 == h { found = 1 } END { exit !found }' "$f"; then known=1; fi
if [ -f "$f" ]; then
	mine=""
	if [ -f "$canon" ] && [ ! -L "$canon" ]; then mine=$(sha256sum "$canon" | cut -d' ' -f1); fi
	if [ "$mine" = "$new" ]; then
		:
	elif [ -n "$mine" ] && python3 -I /usr/local/lib/agentainer/release_version.py newer-default "$ver" "$mine" "$f"; then
		# The file still matches an earlier, older image default, so the user never edited
		# it. A unique temp file keeps the swap atomic; the file keeps its mode.
		tmp=$(mktemp "$HOME/.agentainer/.AGENTS.md.XXXXXX")
		cp /etc/agentainer/AGENTS.md "$tmp"
		chmod "$(stat -c %a "$canon")" "$tmp"
		mv -f "$tmp" "$canon"
		log "the image's default AGENTS.md changed; you had not edited ~/.agentainer/AGENTS.md, so agentainer replaced it with the new default"
	elif [ "$known" = 0 ]; then
		log "the image's default AGENTS.md changed; run 'agentainer-agents diff' to compare"
	fi
fi
# Record this image's default with its version once. A line with a version is added even
# when the hash is already listed without one, so a later older image can compare.
line="$new${ver:+ $ver}"
if ! grep -qxF "$line" "$f" 2>/dev/null; then
	(printf '%s\n' "$line" >>"$f") 2>/dev/null || warn "cannot record the AGENTS.md default version; leaving the ledger alone"
fi
