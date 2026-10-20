#!/bin/sh
# Exercise real container lifecycle operations using an already-built local image.
# shellcheck disable=SC2016 # single-quoted scripts expand inside the container
set -eu
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/../lib.sh"
repo=$(cd "$(dirname "$0")/../.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/cx-launcher.XXXXXX")
name="cx-launcher-$$"
volume="$name-home"
real_runtime=$(command -v "$RUNTIME")
cleanup() {
	"$real_runtime" rm -f "$name" >/dev/null 2>&1 || true
	"$real_runtime" volume rm -f "$volume" >/dev/null 2>&1 || true
	rm -rf "$tmp"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
"$real_runtime" image inspect "$IMAGE" >/dev/null
mkdir -p "$tmp/work space" "$tmp/bin"
chmod 777 "$tmp/work space"
printf '%s\n' 'CX_LAUNCHER_VALUE=retained value' >"$tmp/env"
chmod 600 "$tmp/env"
# The update uses the existing local image. All other operations reach the real engine.
# A registry pull is exercised separately by the published-image verifier.
export CX_TEST_RUNTIME="$real_runtime" CX_TEST_IMAGE="$IMAGE"
wrapper="$tmp/bin/$(basename "$RUNTIME")"
cat >"$wrapper" <<'WRAPPER'
#!/bin/sh
if [ "$#" = 2 ] && [ "$1" = pull ] && [ "$2" = "$CX_TEST_IMAGE" ]; then
	exec "$CX_TEST_RUNTIME" image inspect "$2"
fi
exec "$CX_TEST_RUNTIME" "$@"
WRAPPER
chmod +x "$wrapper"
export AGENTAINER_RUNTIME="$wrapper" AGENTAINER_IMAGE="$IMAGE"
export AGENTAINER_HOME_VOLUME="$volume" AGENTAINER_ENV_FILE="$tmp/env"
launch() { sh "$repo/bin/agentainer" "$@"; }
ready() { "$real_runtime" exec "$name" test -L /var/lib/agentainer/active; }
launch up --name "$name" "$tmp/work space" >/dev/null
wait_for 60 ready
first=$("$real_runtime" inspect --type container --format '{{.Id}}' "$name")
"$real_runtime" exec "$name" sh -ec '
 test "$CX_LAUNCHER_VALUE" = "retained value"
 printf home >"$HOME/launcher-marker"
 printf workspace >/workspace/launcher-marker
'
pass "launcher starts a real container with its env file and workspace"
"$real_runtime" stop "$name" >/dev/null
launch start "$name" >/dev/null
wait_for 60 ready
assert_eq "start preserves container identity" "$first" "$("$real_runtime" inspect --type container --format '{{.Id}}' "$name")"
# Update must use recorded labels, even from another directory with conflicting defaults.
(cd / && AGENTAINER_HOME_VOLUME=cx-unused-home AGENTAINER_ENV_FILE=/cx-missing-env AGENTAINER_IMAGE=localhost/cx-unused:missing launch update "$name") >/dev/null
wait_for 60 ready
second=$("$real_runtime" inspect --type container --format '{{.Id}}' "$name")
[ -n "$first" ] && [ -n "$second" ] && [ "$first" != "$second" ]
pass "update recreates the real container"
assert_eq "update retains home, workspace and original environment" "PRESERVED" "$("$real_runtime" exec "$name" sh -ec 'test "$(cat "$HOME/launcher-marker")" = home; test "$(cat /workspace/launcher-marker)" = workspace; test "$CX_LAUNCHER_VALUE" = "retained value"; echo PRESERVED')"
launch down "$name" >/dev/null
if "$real_runtime" inspect --type container "$name" >/dev/null 2>&1; then
	fail "down removes the container"
else
	pass "down removes the container"
fi
"$real_runtime" volume inspect "$volume" >/dev/null
pass "down retains the home volume"
finish
