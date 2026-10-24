#!/bin/sh
# Downloads URL to OUT and checks it. ALGO is sha256, sha512 or sri (npm "sha512-<base64>").
# Usage: fetch.sh URL ALGO EXPECTED OUT
set -eu
url=$1 algo=$2 expected=$3 out=$4
case "$algo" in
sha256 | sha512 | sri) ;;
*)
	echo "fetch.sh: unknown algorithm $algo" >&2
	exit 2
	;;
esac
if [ -z "$expected" ]; then
	echo "fetch.sh: no expected checksum for $url" >&2
	exit 1
fi
# GET downloads go to a file, so curl can discard partial bytes before retrying.
# https://curl.se/docs/manpage.html#--retry-all-errors
if ! curl -fsSL --proto '=https' --tlsv1.2 --retry 3 --retry-all-errors -o "$out" "$url"; then
	rm -f "$out"
	echo "fetch.sh: download failed: $url" >&2
	exit 1
fi
case "$algo" in
sha256) actual=$(sha256sum "$out" | cut -d' ' -f1) ;;
sha512) actual=$(sha512sum "$out" | cut -d' ' -f1) ;;
sri)
	actual=$(python3 -c 'import base64,hashlib,sys
print("sha512-" + base64.b64encode(hashlib.sha512(open(sys.argv[1], "rb").read()).digest()).decode())' "$out")
	;;
esac
if [ "$actual" != "$expected" ]; then
	echo "fetch.sh: checksum mismatch for $url" >&2
	echo "  expected $expected" >&2
	echo "  actual   $actual" >&2
	rm -f "$out"
	exit 1
fi
