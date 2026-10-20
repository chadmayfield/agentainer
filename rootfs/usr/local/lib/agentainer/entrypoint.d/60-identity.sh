# Step 6: git identity from env, only if none is configured. git needs a committer
# identity in its config even when GIT_AUTHOR_* is set, so the first values are copied.
# Later values differ from the config only for the author, so say so. A value of only
# whitespace counts as unset; step 9 warns about it.
exec 9>"$HOME/.agentainer/.home-config.lock"
if ! flock -w 60 9; then
	warn "another container held the home config lock for 60 seconds; not setting the git identity"
	return 1
fi
for pair in "GIT_AUTHOR_NAME user.name" "GIT_AUTHOR_EMAIL user.email"; do
	var=${pair% *}
	key=${pair#* }
	val=""
	eval "val=\${$var:-}"
	[ -n "$(printf '%s' "$val" | tr -d '[:space:]')" ] || continue
	have=$(git config --global "$key" 9>&- || true)
	if [ -z "$have" ]; then
		git config --global "$key" "$val" 9>&-
	elif [ "$have" != "$val" ]; then
		warn "$var differs from git config $key; commits get the env value as author and the config value as committer"
	fi
done
