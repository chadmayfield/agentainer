#!/bin/sh
# Installs the packages in apt-packages.txt: apt-install.sh. Runs in the Containerfile's apt
# stage with the CA bundle at /tmp/agentainer-build/ca.crt. Reads APT_SNAPSHOT (required) and
# APT_FALLBACK from the environment.
# - First it installs from the pinned snapshot and checks that every installed version came
#   from it (check-apt-snapshot.py).
# - If a snapshot step fails and APT_FALLBACK is "archive", it prints a warning, drops the
#   Snapshot: fields and installs from archive.ubuntu.com as it is today. Any other value of
#   APT_FALLBACK, including empty, makes the build fail.
# - It writes /usr/local/share/agentainer/apt-source, one line: "snapshot <ID>" or
#   "archive-fallback <UTC date> (snapshot <ID> unavailable)".
set -eu
: "${APT_SNAPSHOT:?APT_SNAPSHOT is required}"
export DEBIAN_FRONTEND=noninteractive
B=/tmp/agentainer-build
OUT=/usr/local/share/agentainer
SOURCES=/etc/apt/sources.list.d/ubuntu.sources
KEY=/usr/share/keyrings/ubuntu-archive-keyring.gpg

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
	apt_get update --error-on=any &&
		apt_get upgrade -y &&
		xargs -a "$B/apt-packages.txt" apt-get -o Acquire::Retries=5 -o Acquire::https::CAInfo="$B/ca.crt" \
			-o APT::Get::Always-Include-Phased-Updates=true install -y --no-install-recommends
}

apt_get() {
	apt-get -o Acquire::Retries=5 -o Acquire::https::CAInfo="$B/ca.crt" \
		-o APT::Get::Always-Include-Phased-Updates=true "$@"
}

write_sources "$APT_SNAPSHOT"
if install_all; then
	source_line="snapshot $APT_SNAPSHOT"
	apt-cache policy bash >"$OUT/apt-policy.txt"
	python3 "$B/check-apt-snapshot.py" "$OUT/apt-unpinned.txt"
	sed -i '/^Snapshot: /d' "$SOURCES"
elif [ "${APT_FALLBACK:-}" = archive ]; then
	echo "apt-install.sh: WARNING: the apt snapshot $APT_SNAPSHOT failed; installing from archive.ubuntu.com as it is today. This image is not pinned to the snapshot." >&2
	source_line="archive-fallback $(date -u +%Y-%m-%d) (snapshot $APT_SNAPSHOT unavailable)"
	write_sources
	rm -rf /var/lib/apt/lists/*
	install_all
	apt-cache policy bash >"$OUT/apt-policy.txt"
	# The report is kept, but versions from the archive are expected here.
	python3 "$B/check-apt-snapshot.py" "$OUT/apt-unpinned.txt" || true
else
	echo "apt-install.sh: the apt snapshot $APT_SNAPSHOT failed and APT_FALLBACK is not 'archive'" >&2
	exit 1
fi
printf '%s\n' "$source_line" >"$OUT/apt-source"
rm -rf /var/lib/apt/lists/*
rm -f /var/log/dpkg.log /var/log/alternatives.log /var/log/apt/history.log /var/log/apt/term.log
