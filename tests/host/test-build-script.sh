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
if [ "$1" = run ] && [ -n "${STUB_RUN_FAIL:-}" ]; then
	echo "exec format error" >&2
	exit 126
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
out=$(STUB_RUN_FAIL=1 build 5.6.0)
assert_contains "an image that cannot run says the apt source was not checked" "apt source not checked: the linux/" "$(cat "$T/err")"
out=$(STUB_RUN_FAIL=1 STUB_SERVER=5.6.0 PATH="$T:$PATH" RUNTIME=podman "$B" --platform linux/amd64 2>"$T/err")
assert_contains "the note names the platform" "linux/amd64 image could not be run" "$(cat "$T/err")"

# The Kelos variant gets its own labels and refuses the options it cannot honor.
out=$(STUB_SERVER=5.6.0 PATH="$T:$PATH" RUNTIME=podman "$B" --variant kelos 2>"$T/err")
has_line "kelos builds Containerfile.kelos" "Containerfile.kelos" "$out"
has_line "kelos gets IMAGE_VERSION for its version label" "IMAGE_VERSION=dev" "$out"
has_line "kelos gets the default tag" "localhost/agentainer-kelos:dev" "$out"
if printf '%s\n' "$out" | grep -q '^VCS_REF=.'; then pass "kelos gets VCS_REF"; else fail "kelos gets VCS_REF" "[$out]"; fi
assert_absent "kelos gets no main-image arguments" "$out" "Containerfile.kelos" "AGENT_UID=" "APT_FALLBACK=" "GO_VERSION="
out=$(STUB_SERVER=5.6.0 PATH="$T:$PATH" RUNTIME=podman "$B" --variant kelos --from localhost/agentainer:dev 2>"$T/err")
has_line "--from sets the Kelos base image" "AGENTAINER_IMAGE=localhost/agentainer:dev" "$out"
for opt in "--uid 1001" "--gid 20" "--strict-apt"; do
	# shellcheck disable=SC2086 # the option and its value split on purpose
	STUB_SERVER=5.6.0 PATH="$T:$PATH" RUNTIME=podman "$B" --variant kelos $opt >"$T/out" 2>"$T/err"
	rc=$?
	assert_eq "kelos refuses $opt with exit 2" "2" "$rc"
	assert_contains "kelos names $opt in the refusal" "${opt%% *} cannot be used with --variant kelos" "$(cat "$T/err")"
done
finish
