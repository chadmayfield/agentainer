#!/bin/sh
# Reports an apt snapshot fallback in a CI image build: check-apt-fallback.sh IMAGE.
# Reads /usr/local/share/agentainer/apt-source from IMAGE. If the build fell back to
# archive.ubuntu.com, the script prints a warning annotation, and it fails when the change
# modifies APT_SNAPSHOT in versions.env or build/apt-packages.txt. A release build cannot fall
# back, so a change to those inputs must be proven against the snapshot before it merges.
# The base to compare with comes from EVENT, PR_HEAD, REF and BEFORE, as the "changes" job in
# .github/workflows/build.yml finds it. With no base, the script only warns.
set -eu
image=${1:?image required}
RUNTIME=${RUNTIME:-docker}
line=$("$RUNTIME" run --rm --entrypoint cat "$image" /usr/local/share/agentainer/apt-source)
case "$line" in
archive-fallback*) ;;
*)
	echo "apt source: $line"
	exit 0
	;;
esac
echo "::warning title=apt snapshot fallback::This build used the archive, not the pinned snapshot ($line). CI did not test the snapshot that a release installs from."
base=
case "${EVENT:-}" in
pull_request)
	# The test merge commit's parents are the base branch tip and the pull request head.
	if [ "$(git rev-parse -q --verify 'HEAD^2' || true)" = "${PR_HEAD:-}" ]; then
		base=$(git rev-parse 'HEAD^1')
	fi
	;;
push)
	before=${BEFORE:-}
	if [ -n "$before" ] && [ "$before" != 0000000000000000000000000000000000000000 ] &&
		{ git cat-file -e "$before^{commit}" 2>/dev/null || git fetch -q --depth=1 origin "$before"; }; then
		base=$before
	fi
	;;
esac
if [ -z "$base" ]; then
	echo "No base commit to compare with, so the change was not checked for snapshot edits."
	exit 0
fi
snapshot_lines=$(git diff -U0 --no-renames "$base" HEAD -- versions.env | grep -c '^[-+]APT_SNAPSHOT=' || true)
package_files=$(git diff --name-only --no-renames "$base" HEAD -- build/apt-packages.txt | grep -c . || true)
if [ "$snapshot_lines" -gt 0 ] || [ "$package_files" -gt 0 ]; then
	echo "::error title=apt snapshot fallback::This change modifies APT_SNAPSHOT or build/apt-packages.txt, and the build fell back to the archive, so the new snapshot inputs were not tested. Re-run the build when snapshot.ubuntu.com works."
	exit 1
fi
