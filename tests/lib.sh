#!/bin/sh
# Shared helpers for container tests. Source this file.
RUNTIME=${RUNTIME:-podman}
IMAGE=${IMAGE:-localhost/agentainer:dev}
PLATFORM=${PLATFORM:-}
_failures=0
_count=0

# run_in [runtime run options...] -- command...
# Replaces the first -- with the image name, keeping every argument intact.
run_in() {
	_seen=0
	for _a; do
		shift
		if [ "$_seen" = 0 ] && [ "$_a" = -- ]; then
			set -- "$@" "$IMAGE"
			_seen=1
		else
			set -- "$@" "$_a"
		fi
	done
	[ "$_seen" = 1 ] || {
		echo "run_in: missing --" >&2
		return 2
	}
	"$RUNTIME" run --rm --pull=never ${PLATFORM:+--platform "$PLATFORM"} "$@"
}

# run_bg NAME [runtime run options...]: start a detached test container (respects PLATFORM).
run_bg() {
	_name=$1
	shift
	"$RUNTIME" run -d --pull=never ${PLATFORM:+--platform "$PLATFORM"} --name "$_name" "$@" "$IMAGE" >/dev/null
}

pass() {
	_count=$((_count + 1))
	printf 'ok %s - %s\n' "$_count" "$1"
}

fail() {
	_count=$((_count + 1))
	_failures=$((_failures + 1))
	printf 'not ok %s - %s\n' "$_count" "$1"
	[ -n "${2:-}" ] && printf '  # %s\n' "$2"
	return 0
}

assert_eq() {
	if [ "$2" = "$3" ]; then pass "$1"; else fail "$1" "expected [$2] got [$3]"; fi
}

assert_contains() {
	case "$3" in
	*"$2"*) pass "$1" ;;
	*) fail "$1" "[$2] not found in [$3]" ;;
	esac
}

# assert_absent NAME OUTPUT MARKER NEEDLE...: passes only when OUTPUT contains MARKER
# (proof the command ran) and none of the NEEDLEs. Without the marker, an empty output
# from a command that never ran would look like a pass.
assert_absent() {
	_name=$1 _out=$2 _marker=$3
	shift 3
	case "$_out" in
	*"$_marker"*) ;;
	*)
		fail "$_name" "marker [$_marker] missing, so the command did not run: [$_out]"
		return 0
		;;
	esac
	for _needle; do
		case "$_out" in
		*"$_needle"*)
			fail "$_name" "[$_needle] found in [$_out]"
			return 0
			;;
		esac
	done
	pass "$_name"
}

# wait_for SECONDS COMMAND...: retries COMMAND once a second until it succeeds.
# Returns 1 if it never does.
wait_for() {
	_left=$1
	shift
	while [ "$_left" -gt 0 ]; do
		"$@" >/dev/null 2>&1 && return 0
		_left=$((_left - 1))
		sleep 1
	done
	return 1
}

finish() {
	printf '1..%s\n' "$_count"
	[ "$_failures" -eq 0 ]
}
