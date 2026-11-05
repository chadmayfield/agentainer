#!/bin/sh
# Host-side tests for scripts/build.sh. A stub podman on PATH reports the server
# version from STUB_SERVER and prints each build argument on its own line, so
# nothing is built.
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/../lib.sh"
B="$(cd "$(dirname "$0")/../.." && pwd)/scripts/build.sh"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
trap 'exit 130' INT TERM
cat >"$T/podman" <<'EOF'
#!/bin/sh
if [ "$1" = info ]; then
	printf '%s\n' "$STUB_SERVER"
	exit 0
fi
if [ "$1" = run ]; then
	printf '%s\n' "${STUB_APT_SOURCE:-snapshot 20261104T000000Z}"
	exit 0
fi
printf '%s\n' "$@"
EOF
chmod +x "$T/podman"
cp "$T/podman" "$T/docker"
# stdout holds the build arguments; stderr holds the trace and warnings.
build() { STUB_SERVER=$1 PATH="$T:$PATH" RUNTIME=podman "$B" 2>"$T/err"; }
has_line() { # NAME EXACT-LINE OUTPUT
	if printf '%s\n' "$3" | grep -qxF -- "$2"; then pass "$1"; else fail "$1" "no line [$2] in [$3]"; fi
}
epoch=$(sed -n 's/^SOURCE_DATE_EPOCH=//p' "$(dirname "$B")/../versions.env")

out=$(build 5.6.0)
has_line "5.6 server gets --source-date-epoch" "--source-date-epoch" "$out"
has_line "epoch value comes from versions.env" "$epoch" "$out"
has_line "5.6 server gets --rewrite-timestamp" "--rewrite-timestamp" "$out"
assert_absent "5.6 server prints no warning" "$(cat "$T/err")" "build -f Containerfile" "file times"

out=$(build 6.1.0)
has_line "6.1 server gets --rewrite-timestamp" "--rewrite-timestamp" "$out"

out=$(build 5.3.2)
has_line "5.3 server still gets the docker format" "docker" "$out"
assert_absent "5.3 server gets no timestamp flags" "$out" "--format" "--source-date-epoch" "--rewrite-timestamp"
assert_contains "5.3 server warning names the version" "5.3.2" "$(cat "$T/err")"

out=$(build "")
assert_absent "unknown server version gets no timestamp flags" "$out" "--format" "--rewrite-timestamp"
assert_contains "unknown server version warns" "file times" "$(cat "$T/err")"

out=$(build 5.6.0)
has_line "pins the Containerfile declares are passed" "GO_VERSION=$(sed -n 's/^GO_VERSION=//p' "$(dirname "$B")/../versions.env")" "$out"
assert_absent "pins the Containerfile does not declare are left out" "$out" "--format" "CONTAINERSSH_IMAGE=" "SOURCE_DATE_EPOCH="

out=$(PATH="$T:$PATH" RUNTIME=docker "$B" 2>"$T/err")
has_line "Docker builds keep Docker media types for Podman health checks" "--output=type=image,oci-mediatypes=false" "$out"
has_line "local Docker builds disable incompatible inline attestations" "--provenance=false" "$out"
assert_absent "Docker builds get no Podman options" "$out" "build" "--format" "--source-date-epoch" "--rewrite-timestamp"

# Local builds fall back to archive.ubuntu.com when the snapshot is down. APT_FALLBACK= (empty)
# in the environment asks for a strict build, and --strict-apt does the same.
out=$(build 5.6.0)
has_line "default build allows the archive fallback" "APT_FALLBACK=archive" "$out"
out=$(APT_FALLBACK='' build 5.6.0)
assert_absent "APT_FALLBACK= in the environment builds strict" "$out" "--format" "APT_FALLBACK="
out=$(APT_FALLBACK=other build 5.6.0)
has_line "another APT_FALLBACK value is passed through for the Containerfile to refuse" "APT_FALLBACK=other" "$out"
out=$(STUB_SERVER=5.6.0 PATH="$T:$PATH" RUNTIME=podman "$B" --strict-apt 2>"$T/err")
assert_absent "--strict-apt builds strict" "$out" "--format" "APT_FALLBACK="
out=$(STUB_SERVER=5.6.0 PATH="$T:$PATH" RUNTIME=podman "$B" --no-cache 2>"$T/err")
has_line "--no-cache is passed to the build" "--no-cache" "$out"
assert_absent "a snapshot build prints no fallback warning" "$(cat "$T/err")" "build -f Containerfile" "archive-fallback"
out=$(STUB_APT_SOURCE='archive-fallback 2026-11-05 (snapshot 20261104T000000Z unavailable)' build 5.6.0)
assert_contains "a fallback build warns and names the --no-cache rebuild" "--no-cache" "$(cat "$T/err")"
assert_contains "the fallback warning quotes the record" "archive-fallback 2026-11-05" "$(cat "$T/err")"
finish
