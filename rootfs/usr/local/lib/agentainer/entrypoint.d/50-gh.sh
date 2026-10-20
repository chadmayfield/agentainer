# Step 5: use gh as the git credential helper when a GitHub token is set.
# gh reads GH_TOKEN, then GITHUB_TOKEN ("gh help environment").
[ -n "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ] || return 0
# Containers sharing a home volume take turns on ~/.gitconfig: git fails with "could not
# lock config file" while another writer holds it, and two setup-git runs add the helper
# twice. Steps 6 and 7 use the same lock. Children get fd 9 closed so none keeps the lock.
exec 9>"$HOME/.agentainer/.home-config.lock"
if ! flock -w 60 9; then
	warn "another container held the home config lock for 60 seconds; not setting up gh for git"
	return 1
fi
# Skip it when this container's gh already is the helper, since setup-git rewrites
# ~/.gitconfig every time. setup-git writes
# credential.https://github.com.helper = !<path to gh> auth git-credential, so a helper
# naming another gh (for example from a host's ~/.gitconfig) still gets replaced.
if git config --global --get-all credential.https://github.com.helper 2>/dev/null |
	grep -qxF "!$(command -v gh) auth git-credential"; then
	return 0
fi
gh auth setup-git 9>&-
