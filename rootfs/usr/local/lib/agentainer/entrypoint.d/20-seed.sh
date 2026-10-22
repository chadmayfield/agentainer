# Step 2: seed files that are missing. Never overwrite. A path the user already uses
# for something else is reported and skipped.
# Serialize missing-file checks and copies on a shared home.
if ! (: >>"$HOME/.agentainer/.seed.lock") 2>/dev/null; then
	warn "cannot open the seed lock; skipping seeding"
	return 0
fi
exec 9>>"$HOME/.agentainer/.seed.lock"
flock -w 30 9
try_seed() {
	seed_file "$1" "$2" 2>/dev/null || warn "could not seed $2 (something else is in the way); skipping"
}
src=/etc/agentainer/home
find "$src" -type f | while IFS= read -r f; do
	try_seed "$f" "$HOME/${f#"$src"/}"
done
# A fresh volume or PVC hides the image's dotfiles, so seed the shell defaults too.
# .profile comes from /etc/agentainer/home, which puts personal bin directories last in
# PATH; the rest comes from /etc/skel.
for f in .bashrc .bash_logout; do
	if [ -f "/etc/skel/$f" ]; then try_seed "/etc/skel/$f" "$HOME/$f"; fi
done
if [ -f /etc/agentainer/seed/mcp.json ]; then
	try_seed /etc/agentainer/seed/mcp.json "$HOME/.agentainer/mcp.json"
fi
