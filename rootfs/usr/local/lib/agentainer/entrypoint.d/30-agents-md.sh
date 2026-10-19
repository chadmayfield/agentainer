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
		# Another container on the same home volume may have made the same link first.
		if [ "$(readlink "$target" 2>/dev/null)" != "$canon" ]; then
			warn "could not link $target (something else is in the way); skipping"
		fi
	fi
done

# agents-default.sha256 lists every image default this home has seen, one per line as
# "<sha256> <image version>". Lines with only a hash come from images that did not record
# a version; their version counts as unknown, older than any release.
# An unedited file follows the image's default only when this image is a release
# (YYYY.MM.DD or YYYY.MM.DD.N) newer than every image that shipped the file's current
# content, so an older image on a shared home volume never rolls the file back.

# awk function key(VERSION): a 14-digit string that orders release versions, or 14 zeros
# for any other version. Equal-length strings compare like the numbers they spell.
KEY='function key(v, p) {
	if (v !~ /^[0-9][0-9][0-9][0-9]\.[0-9][0-9]\.[0-9][0-9](\.[0-9]+)?$/) return "00000000000000"
	split(v, p, ".")
	return sprintf("%04d%02d%02d%06d", p[1], p[2], p[3], p[4])
}'
# newest_key HASH FILE: the highest key recorded for HASH in FILE.
newest_key() {
	awk -v h="$1" "$KEY"'
		$1 == h && key($2) > best { best = key($2) }
		END { print (best == "" ? "00000000000000" : best) }' "$2"
}

new=$(sha256sum /etc/agentainer/AGENTS.md | cut -d' ' -f1)
ver=${AGENTAINER_IMAGE_VERSION:-}
f="$HOME/.agentainer/agents-default.sha256"
# Containers sharing the home volume take turns, so each one decides on a file and a hash
# list that no other container is changing.
exec 9>"$HOME/.agentainer/.agents-md.lock"
if ! flock -w 30 9; then
	warn "another container held the AGENTS.md lock for 30 seconds; not checking the default now"
	return 0
fi
known=0
if [ -f "$f" ] && awk -v h="$new" '$1 == h { found = 1 } END { exit !found }' "$f"; then known=1; fi
if [ -f "$f" ]; then
	mine=""
	if [ -f "$canon" ] && [ ! -L "$canon" ]; then mine=$(sha256sum "$canon" | cut -d' ' -f1); fi
	if [ "$mine" = "$new" ]; then
		:
	elif [ -n "$mine" ] && awk -v h="$mine" '$1 == h { found = 1 } END { exit !found }' "$f" &&
		[ "$(awk -v v="$ver" "$KEY"' BEGIN { print key(v) }')" -gt "$(newest_key "$mine" "$f")" ]; then
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
if ! grep -qxF "$line" "$f" 2>/dev/null; then printf '%s\n' "$line" >>"$f"; fi
