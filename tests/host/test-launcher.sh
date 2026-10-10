#!/bin/sh
# Host-side tests for bin/agentainer. A stub runtime prints one argument per line, so
# quoting and argument-splitting bugs show up. No containers are started.
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/../lib.sh"
L="$(cd "$(dirname "$0")/../.." && pwd)/bin/agentainer"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT INT TERM
printf '#!/bin/sh\nprintf "%%s\\n" "$@"\n' >"$T/podman"
cp "$T/podman" "$T/docker"
chmod +x "$T/podman" "$T/docker"
export AGENTAINER_ENV_FILE=/nonexistent
# stdout only: the trace and warnings go to stderr; tests that check them add 2>&1.
pod() { AGENTAINER_RUNTIME="$T/podman" sh "$L" "$@"; }
dock() { AGENTAINER_RUNTIME="$T/docker" sh "$L" "$@"; }
has_line() { # NAME EXACT-LINE OUTPUT
	if printf '%s\n' "$3" | grep -qxF -- "$2"; then pass "$1"; else fail "$1" "no line [$2] in [$3]"; fi
}

mkdir -p "$T/my code" "$T/cdp/code" "$T/here/code"
out=$(pod up "$T/my code")
has_line "podman keep-id" "--userns=keep-id:uid=1000,gid=1000" "$out"
has_line "sudo off by default" "no-new-privileges=true" "$out"
has_line "path with a space stays one argument" "$(cd "$T/my code" && pwd -P):/workspace" "$out"
has_line "sysctl value stays one argument" "net.ipv4.ping_group_range=1000 1000" "$out"
has_line "home volume" "agentainer-home:/home/agent" "$out"
has_line "default name" "agentainer" "$out"
has_line "containers are labelled for status" "io.github.chadmayfield.agentainer=1" "$out"
has_line "image is last" "ghcr.io/chadmayfield/agentainer:latest" "$(printf '%s\n' "$out" | tail -1)"
has_line "relative DIR becomes absolute" "$(cd "$T/here/code" && pwd -P):/workspace" "$(cd "$T/here" && pod up code)"
has_line "CDPATH is ignored" "$(cd "$T/here/code" && pwd -P):/workspace" "$(cd "$T/here" && CDPATH="$T/cdp" pod up code)"
assert_contains "missing DIR fails" "no such directory" "$(pod up "$T/nonexistent" 2>&1 || true)"
assert_contains "option after DIR is rejected" "usage" "$(pod up "$T/my code" --sudo 2>&1 || true)"
assert_contains "extra argument is rejected" "usage" "$(pod up "$T/my code" junk 2>&1 || true)"
assert_contains "missing option value is rejected" "usage" "$(pod up --name 2>&1 || true)"
has_line "--image is used" "example.com/other:1" "$(pod up --image example.com/other:1 "$T/my code")"
has_line "home volume can be overridden" "abtest-home:/home/agent" "$(AGENTAINER_HOME_VOLUME=abtest-home pod up "$T/my code")"

out=$(dock up --sudo --name proj "$T/my code")
case "$out" in
*keep-id*) fail "no keep-id on docker" ;;
*) pass "no keep-id on docker" ;;
esac
case "$out" in
*no-new-privileges*) fail "--sudo drops no-new-privileges" ;;
*) pass "--sudo drops no-new-privileges" ;;
esac
has_line "custom name" "proj" "$out"

envf="$T/env"
: >"$envf"
chmod 600 "$envf"
has_line "uses the env file when present" "$envf" "$(AGENTAINER_ENV_FILE=$envf pod up "$T/my code" 2>&1)"
chmod 400 "$envf"
assert_eq "mode 400 is accepted quietly" "none" "$(AGENTAINER_ENV_FILE=$envf pod up "$T/my code" 2>&1 | grep "should" || echo none)"
chmod 644 "$envf"
assert_contains "warns about a readable env file" "should not be readable by others" "$(AGENTAINER_ENV_FILE=$envf pod up "$T/my code" 2>&1)"
ln -s "$envf" "$T/envlink"
chmod 600 "$envf"
assert_eq "a symlinked 600 env file is accepted quietly" "none" "$(AGENTAINER_ENV_FILE=$T/envlink pod up "$T/my code" 2>&1 | grep "should" || echo none)"

assert_eq "attach uses tmux" "exec|-it|agentainer|tmux|new-session|-A|-s|main" "$(pod attach | paste -sd '|' -)"
assert_eq "down keeps the home volume" "rm|-f|agentainer" "$(pod down | paste -sd '|' -)"
has_line "status filters on the label" "label=io.github.chadmayfield.agentainer=1" "$(pod status)"
assert_contains "unknown command fails" "usage" "$(sh "$L" bogus 2>&1 || true)"
assert_contains "no runtime found is an error" "neither podman nor docker" "$(AGENTAINER_RUNTIME='' PATH=/nonexistent /bin/sh "$L" status 2>&1 || true)"

finish
