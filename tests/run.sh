#!/bin/sh
# Runs every tests/NN-*.sh file, or the files given as arguments.
set -u
cd "$(dirname "$0")/.." || exit 2
status=0
out=$(mktemp) && rc_file=$(mktemp) || exit 2
trap 'rm -f "$out" "$rc_file"' EXIT
if [ "$#" -eq 0 ]; then set -- tests/[0-9][0-9]-*.sh; fi
for t in "$@"; do
	printf '# %s\n' "$t"
	# tee keeps the output streaming; the exit status goes through a file because a
	# POSIX pipeline returns the status of its last command.
	{
		sh "$t"
		echo "$?" >"$rc_file"
	} | tee "$out"
	rc=$(cat "$rc_file")
	if [ "$rc" != 0 ]; then
		status=1
		# A file that dies before it reports a failure, for example on a syntax error
		# or a failed setup step, still shows up as a failure in the TAP output.
		if ! grep -q '^not ok' "$out"; then
			printf 'not ok - exited with status %s without reporting a failing test\n' "$rc"
		fi
	fi
done
exit "$status"
