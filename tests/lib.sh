#!/bin/sh
# Shared helpers for container tests. Source this file.
RUNTIME=${RUNTIME:-podman}
IMAGE=${IMAGE:-localhost/agentbox:dev}
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
	"$RUNTIME" run --rm ${PLATFORM:+--platform "$PLATFORM"} "$@"
}

# run_bg NAME [runtime run options...]: start a detached test container (respects PLATFORM).
run_bg() {
	_name=$1
	shift
	"$RUNTIME" run -d ${PLATFORM:+--platform "$PLATFORM"} --name "$_name" "$@" "$IMAGE" >/dev/null
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

finish() {
	printf '1..%s\n' "$_count"
	[ "$_failures" -eq 0 ]
}
