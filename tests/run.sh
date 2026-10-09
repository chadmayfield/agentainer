#!/bin/sh
# Runs every tests/NN-*.sh file, or the files given as arguments.
set -u
cd "$(dirname "$0")/.." || exit 2
status=0
if [ "$#" -eq 0 ]; then set -- tests/[0-9][0-9]-*.sh; fi
for t in "$@"; do
	printf '# %s\n' "$t"
	sh "$t" || status=1
done
exit "$status"
