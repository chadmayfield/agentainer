#!/bin/sh
# Installs the packages in apt-packages.txt: apt-install.sh. Runs in the Containerfile's apt
# stage with the CA bundle at /tmp/agentainer-build/ca.crt. Reads APT_SNAPSHOT (required) and
# APT_FALLBACK from the environment.
# - First it installs from the pinned snapshot and checks that every installed version came
#   from it (check-apt-snapshot.py).
# - If any of those steps fails and APT_FALLBACK is "archive", it prints a warning, repairs
#   a half-finished dpkg run, drops the Snapshot: fields and installs from archive.ubuntu.com
#   as it is today. Any other value of APT_FALLBACK, including empty, makes the build fail.
# - It writes /usr/local/share/agentainer/apt-source, one line: "snapshot <ID>" or
#   "archive-fallback <UTC date> (snapshot <ID> unavailable)".
# APT_INSTALL_ROOT (empty in the image) prefixes every path, so tests/host/test-apt-install.sh
# can run the script against a scratch tree.
set -eu
: "${APT_SNAPSHOT:?APT_SNAPSHOT is required}"
export DEBIAN_FRONTEND=noninteractive
P=${APT_INSTALL_ROOT:-}
B=$P/tmp/agentainer-build
OUT=$P/usr/local/share/agentainer
SOURCES=$P/etc/apt/sources.list.d/ubuntu.sources
KEY=/usr/share/keyrings/ubuntu-archive-keyring.gpg
APT_OPTS="-o Acquire::Retries=5 -o Acquire::https::CAInfo=$B/ca.crt -o APT::Get::Always-Include-Phased-Updates=true"

# write_sources [SNAPSHOT]: with an ID, each source carries a "Snapshot: ID" field
# (apt sources.list(5)); without one, the sources track the live archive.
write_sources() {
	{
		printf 'Types: deb\nURIs: http://archive.ubuntu.com/ubuntu/\nSuites: resolute resolute-updates resolute-backports\nComponents: main universe restricted multiverse\nSigned-By: %s\n' "$KEY"
		[ -z "${1:-}" ] || printf 'Snapshot: %s\n' "$1"
		printf '\nTypes: deb\nURIs: http://security.ubuntu.com/ubuntu/\nSuites: resolute-security\nComponents: main universe restricted multiverse\nSigned-By: %s\n' "$KEY"
		[ -z "${1:-}" ] || printf 'Snapshot: %s\n' "$1"
	} >"$SOURCES"
}

# install_all: the apt steps, chained with && so a failure returns non-zero even when the
# caller tests the result (errexit is off in that case).
install_all() {
	# $APT_OPTS holds no quoted or empty values, so it splits into separate words.
	# shellcheck disable=SC2086
	apt-get $APT_OPTS update --error-on=any &&
		apt-get $APT_OPTS upgrade -y &&
		xargs apt-get $APT_OPTS install -y --no-install-recommends <"$B/apt-packages.txt"
}

# from_snapshot: install, then require every installed version to come from the snapshot.
from_snapshot() {
	install_all &&
		apt-cache policy bash >"$OUT/apt-policy.txt" &&
		python3 "$B/check-apt-snapshot.py" "$OUT/apt-unpinned.txt"
}

write_sources "$APT_SNAPSHOT"
if from_snapshot; then
	source_line="snapshot $APT_SNAPSHOT"
	sed '/^Snapshot: /d' "$SOURCES" >"$SOURCES.new"
	mv "$SOURCES.new" "$SOURCES"
elif [ "${APT_FALLBACK:-}" = archive ]; then
	echo "apt-install.sh: WARNING: the apt snapshot $APT_SNAPSHOT failed; installing from archive.ubuntu.com as it is today. This image is not pinned to the snapshot." >&2
	source_line="archive-fallback $(date -u +%Y-%m-%d) (snapshot $APT_SNAPSHOT unavailable)"
	# A failure during dpkg can leave packages unpacked but not configured, and apt refuses to
	# continue until they are (dpkg(1) --configure -a; apt-get(8) --fix-broken). If a step here
	# fails, the install below fails the build.
	dpkg --configure -a || true
	# shellcheck disable=SC2086
	apt-get $APT_OPTS --fix-broken install -y || true
	write_sources
	rm -rf "$P"/var/lib/apt/lists/*
	install_all
	apt-cache policy bash >"$OUT/apt-policy.txt"
	# The report is kept, but versions from the archive are expected here.
	python3 "$B/check-apt-snapshot.py" "$OUT/apt-unpinned.txt" || true
else
	echo "apt-install.sh: the apt snapshot $APT_SNAPSHOT failed and APT_FALLBACK is not 'archive'" >&2
	exit 1
fi
printf '%s\n' "$source_line" >"$OUT/apt-source"
rm -rf "$P"/var/lib/apt/lists/*
rm -f "$P"/var/log/dpkg.log "$P"/var/log/alternatives.log "$P"/var/log/apt/history.log "$P"/var/log/apt/term.log
