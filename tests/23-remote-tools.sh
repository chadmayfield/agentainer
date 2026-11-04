#!/bin/sh
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"
# shellcheck source=versions.env
. "$(dirname "$0")/../versions.env"

# Prints "name=status" for each package, so a failure names the package.
pkg_status() {
	# shellcheck disable=SC2016 # expands in the container
	run_in --network none -- sh -c '
		for p in "$@"; do
			printf "%s=%s\n" "$p" "$(dpkg-query -W -f="\${Status}" "$p" 2>/dev/null)"
		done' sh "$@"
}

expect_installed() {
	_name=$1
	shift
	_want=""
	for _p; do
		_want="${_want}${_p}=install ok installed
"
	done
	assert_eq "$_name" "${_want%
}" "$(pkg_status "$@")"
}

# Playwright v1.64.1, nativeDeps.ts, entry 'ubuntu26.04-x64', "chromium" list.
expect_installed "chromium libraries installed" \
	libasound2t64 libatk-bridge2.0-0t64 libatk1.0-0t64 libatspi2.0-0t64 libcairo2 \
	libcups2t64 libdbus-1-3 libdrm2 libgbm1 libglib2.0-0t64 libnspr4 libnss3 \
	libpango-1.0-0 libx11-6 libxcb1 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
	libxkbcommon0 libxrandr2

# Same entry, "tools" list without xvfb.
expect_installed "fonts installed" \
	fonts-noto-color-emoji fonts-unifont libfontconfig1 libfreetype6 xfonts-cyrillic \
	xfonts-scalable fonts-liberation fonts-ipafont-gothic fonts-wqy-zenhei \
	fonts-tlwg-loma-otf fonts-freefont-ttf

expect_installed "sftp server, poppler and imagemagick installed" \
	openssh-sftp-server poppler-utils imagemagick

# dpkg-query exits 1 for a package that is not installed; rc=127 (missing command) or any
# other code fails the marker.
# "not installed" text from dpkg contains the package name, so check the status string.
# shellcheck disable=SC2016 # expands in the container
_xvfb=$(run_in --network none -- sh -c 'dpkg-query -W -f="\${Status}" xvfb 2>&1; echo "ran rc=$? end"')
assert_absent "xvfb is not installed" "$_xvfb" "ran rc=1 end" "install ok installed"

assert_eq "playwright mcp uses chromium" "chromium" \
	"$(run_in --network none -- printenv PLAYWRIGHT_MCP_BROWSER)"

# shellcheck disable=SC2016 # expands in the container
assert_eq "pdftotext, pdftoppm and magick run" "0 0 0" "$(run_in --network none -- sh -c '
	pdftotext -v >/dev/null 2>&1; a=$?
	pdftoppm -v >/dev/null 2>&1; b=$?
	magick -version >/dev/null 2>&1; c=$?
	echo "$a $b $c"')"

assert_eq "sftp-server is executable" "yes" \
	"$(run_in --network none -- sh -c 'test -x /usr/lib/openssh/sftp-server && echo yes')"

assert_contains "gosec version" "Version: $GOSEC_VERSION" "$(run_in --network none -- gosec --version 2>&1)"
assert_contains "gitleaks version" "$GITLEAKS_VERSION" "$(run_in --network none -- gitleaks version)"

# main.go:48-50 at containerssh/agent v0.11.0 prints the help text and exits 0 for --help.
assert_eq "containerssh-agent --help exits 0" "rc=0" \
	"$(run_in --network none -- sh -c '/usr/local/bin/containerssh-agent --help >/dev/null 2>&1; echo rc=$?')"
# shellcheck disable=SC2016 # expands in the container
assert_eq "/usr/bin/containerssh-agent resolves to the pinned binary" "/usr/local/bin/containerssh-agent" \
	"$(run_in --network none -- sh -c 'readlink -f /usr/bin/containerssh-agent')"

finish
