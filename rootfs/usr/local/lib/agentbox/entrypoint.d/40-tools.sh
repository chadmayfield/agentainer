# Step 4: point /var/lib/agentbox/active at the tools root for AGENTBOX_TOOLS.
# The link lives in the container's own filesystem, not on the home volume, so
# containers that share a home volume keep their own mode.
mode=${AGENTBOX_TOOLS:-ephemeral}
case "$mode" in
ephemeral) root=/var/lib/agentbox/tools ;;
persist) root="$HOME/.agentbox/tools" ;;
*)
	warn "AGENTBOX_TOOLS=$mode is not ephemeral or persist; using ephemeral"
	mode=ephemeral
	root=/var/lib/agentbox/tools
	;;
esac
mkdir -p "$root/bin" "$root/npm/bin"
active=/var/lib/agentbox/active
if [ -e "$active" ] && [ ! -L "$active" ]; then
	warn "$active was a real directory; moving it to $active.$$.bak"
	mv "$active" "$active.$$.bak"
fi
ln -sfn "$root" "$active.new.$$"
mv -T "$active.new.$$" "$active"

current=$(sha256sum /usr/local/share/agentbox/versions.env | cut -d' ' -f1)
printf '%s\n' "$current" >"$HOME/.agentbox/image-version"
if [ "$mode" = persist ]; then
	tstamp="$HOME/.agentbox/tools-image-version"
	persisted=""
	for d in bin npm/bin python/bin; do
		names=$(find "$HOME/.agentbox/tools/$d" -mindepth 1 -maxdepth 1 -exec basename {} \; 2>/dev/null | tr '\n' ' ')
		if [ -n "$names" ]; then persisted="$persisted $names"; fi
	done
	if [ -z "$persisted" ]; then
		# Nothing persisted yet: tools installed from now on belong to this image.
		printf '%s\n' "$current" >"$tstamp"
	elif [ "$(cat "$tstamp" 2>/dev/null)" != "$current" ]; then
		# Repeats on every start until the user runs agentbox-tools reset.
		warn "image changed since these persisted tools were installed:$persisted"
		warn "run 'agentbox-tools reset' to move them aside"
	fi
fi
