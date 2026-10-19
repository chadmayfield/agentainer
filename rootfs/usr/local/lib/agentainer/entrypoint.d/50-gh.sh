# Step 5: use gh as the git credential helper when a GitHub token is set (spec 6.2).
# gh reads GH_TOKEN, then GITHUB_TOKEN ("gh help environment").
[ -n "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ] || return 0
# Skip it when this container's gh already is the helper: setup-git rewrites ~/.gitconfig
# every time, and containers sharing a home volume may start at once. setup-git writes
# credential.https://github.com.helper = !<path to gh> auth git-credential, so a helper
# naming another gh (for example from a host's ~/.gitconfig) still gets replaced.
if git config --global --get-all credential.https://github.com.helper 2>/dev/null |
	grep -qxF "!$(command -v gh) auth git-credential"; then
	return 0
fi
gh auth setup-git
