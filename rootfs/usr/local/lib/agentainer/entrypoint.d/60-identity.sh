# Step 6: git identity from env, only if none is configured. git needs a committer
# identity in its config even when GIT_AUTHOR_* is set, so the first values are copied.
# Later values differ from the config only for the author, so say so.
for pair in "GIT_AUTHOR_NAME user.name" "GIT_AUTHOR_EMAIL user.email"; do
	var=${pair% *}
	key=${pair#* }
	eval "val=\${$var:-}"
	[ -n "$val" ] || continue
	have=$(git config --global "$key" || true)
	if [ -z "$have" ]; then
		git config --global "$key" "$val"
	elif [ "$have" != "$val" ]; then
		warn "$var differs from git config $key; commits get the env value as author and the config value as committer"
	fi
done
