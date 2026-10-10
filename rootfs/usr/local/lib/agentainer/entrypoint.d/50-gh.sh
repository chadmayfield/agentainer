# Step 5: use gh as the git credential helper when a GitHub token is set (spec 6.2).
# gh reads GH_TOKEN, then GITHUB_TOKEN ("gh help environment").
[ -n "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ] || return 0
gh auth setup-git
