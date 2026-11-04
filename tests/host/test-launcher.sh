#!/bin/sh
# Host-side tests for bin/agentainer. A stub runtime prints one argument per line, so
# quoting and argument-splitting bugs show up. No containers are started.
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/../lib.sh"
L="$(cd "$(dirname "$0")/../.." && pwd)/bin/agentainer"
T=$(cd "$(mktemp -d)" && pwd -P) # resolved, as the launcher resolves paths
trap 'rm -rf "$T"' EXIT INT TERM
cat >"$T/podman" <<'EOF'
#!/bin/sh
if [ "$1" = inspect ]; then echo 1; else printf '%s\n' "$@"; fi
EOF
cp "$T/podman" "$T/docker"
chmod +x "$T/podman" "$T/docker"
export AGENTAINER_ENV_FILE=/nonexistent
# The host's locale and time zone would otherwise reach the dry-run output.
unset LANG LC_ALL LC_CTYPE LC_NUMERIC LC_TIME LC_COLLATE LC_MONETARY LC_MESSAGES \
	LC_PAPER LC_NAME LC_ADDRESS LC_TELEPHONE LC_MEASUREMENT LC_IDENTIFICATION TZ
export AGENTAINER_LOCALTIME="$T/no-localtime"
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
# A home given as a path is mounted and recorded as an absolute path, so update from
# another directory mounts the same one.
mkdir -p "$T/here/home"
out=$(cd "$T/here" && AGENTAINER_HOME_VOLUME=./home pod up "$T/my code")
has_line "a relative home path is mounted as an absolute path" "$T/here/home:/home/agent" "$out"
has_line "a relative home path is recorded as an absolute path" "io.github.chadmayfield.agentainer.home=$T/here/home" "$out"
assert_contains "a missing home path fails" "no such directory: ./nohome" "$(cd "$T/here" && AGENTAINER_HOME_VOLUME=./nohome pod up "$T/my code" 2>&1 || true)"
assert_eq "a missing home path runs nothing" "" "$(cd "$T/here" && AGENTAINER_HOME_VOLUME=./nohome pod up "$T/my code" 2>/dev/null || true)"

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
# The image name is the last argument of the run command, so it proves the launcher got that far.
assert_absent "mode 400 is accepted quietly" "$(AGENTAINER_ENV_FILE=$envf pod up "$T/my code" 2>&1)" \
	ghcr.io/chadmayfield/agentainer:latest "should"
chmod 644 "$envf"
assert_contains "warns about a readable env file" "should not be readable by others" "$(AGENTAINER_ENV_FILE=$envf pod up "$T/my code" 2>&1)"
ln -s "$envf" "$T/envlink"
chmod 600 "$envf"
assert_absent "a symlinked 600 env file is accepted quietly" "$(AGENTAINER_ENV_FILE=$T/envlink pod up "$T/my code" 2>&1)" \
	ghcr.io/chadmayfield/agentainer:latest "should"

assert_eq "attach uses tmux" "exec|-it|agentainer|tmux|new-session|-A|-s|main" "$(pod attach | paste -sd '|' -)"
assert_eq "shell opens a bash login shell" "exec|-it|agentainer|bash|-l" "$(pod shell | paste -sd '|' -)"
has_line "AGENTAINER_IMAGE sets the image" "example.com/x:1" "$(AGENTAINER_IMAGE=example.com/x:1 pod up "$T/my code")"
assert_eq "down keeps the home volume" "rm|-f|agentainer" "$(pod down | paste -sd '|' -)"
has_line "status filters on the label" "label=io.github.chadmayfield.agentainer=1" "$(pod status)"
mkdir -p "$T/a:b"
assert_contains "DIR with a colon is rejected" "contains ':'" "$(pod up "$T/a:b" 2>&1 || true)"
assert_eq "DIR with a colon runs nothing" "" "$(pod up "$T/a:b" 2>/dev/null || true)"

# Physical paths still contain the colon when reached through a symlink.
ln -s "$T/a:b" "$T/colon-link"
out=$(pod up "$T/colon-link" 2>&1 || true)
assert_absent "colon DIR message does not recommend a symlink" "$out" "contains ':'" "symlink"
assert_contains "colon DIR message recommends renaming" "rename" "$out"
out=$(AGENTAINER_HOME_VOLUME="$T/colon-link" pod up "$T/my code" 2>&1 || true)
assert_absent "colon home message does not recommend a symlink" "$out" "contains ':'" "symlink"

# up records its options as labels, so update can recreate the container.
out=$(AGENTAINER_HOME_VOLUME=h2 pod up --sudo --name proj --image example.com/i:2 "$T/my code")
has_line "up records DIR" "io.github.chadmayfield.agentainer.dir=$(cd "$T/my code" && pwd -P)" "$out"
has_line "up records the image" "io.github.chadmayfield.agentainer.image=example.com/i:2" "$out"
has_line "up records --sudo" "io.github.chadmayfield.agentainer.sudo=1" "$out"
has_line "up records the home volume" "io.github.chadmayfield.agentainer.home=h2" "$out"
has_line "up records no env file" "io.github.chadmayfield.agentainer.env-file=" "$out"
has_line "up records the env file" "io.github.chadmayfield.agentainer.env-file=$envf" "$(AGENTAINER_ENV_FILE=$envf pod up "$T/my code" 2>/dev/null)"

assert_eq "start starts a stopped container" "start|agentainer" "$(pod start | paste -sd '|' -)"
assert_eq "start takes a name" "start|proj" "$(pod start proj | paste -sd '|' -)"

# A stub that answers "inspect" from files in $T/labels, named after the label.
mkdir -p "$T/labels"
cat >"$T/insp" <<'EOF'
#!/bin/sh
if [ "$1" = inspect ]; then
	case "$*" in
	*'.State.Running'*) echo true; exit 0 ;;
	*'.Id'*) echo cx-previous-container; exit 0 ;;
	esac
	printf '%s\n' "$*" >>"$LABELS.calls"
	shift
	fmt="" obj=""
	while [ "$#" -gt 0 ]; do
		case "$1" in
		--format) fmt=$2; shift 2 ;;
		--type) shift 2 ;;
		--) shift ;;
		*) obj=$1; shift ;;
		esac
	done
	k=$(printf '%s' "$fmt" | sed 's/.*"\(.*\)".*/\1/')
	[ -f "$LABELS/$obj" ] || { echo "no such object: $obj" >&2; exit 1; }
	sed -n "s|^$k=||p" "$LABELS/$obj"
	exit 0
fi
printf '%s\n' "$@"
echo ---
EOF
chmod +x "$T/insp"
ins() { LABELS="$T/labels" AGENTAINER_RUNTIME="$T/insp" sh "$L" "$@"; }
p=io.github.chadmayfield.agentainer
printf '%s\n' "$p.dir=$T/my code" "$p.image=example.com/i:2" "$p.sudo=1" "$p.home=h2" "$p.env-file=$envf" >"$T/labels/proj"
out=$(AGENTAINER_HOME_VOLUME=other AGENTAINER_ENV_FILE=/nonexistent ins update proj 2>/dev/null)
assert_eq "update retains a backup until replacement startup" "pull|rename|stop|run|exec|rm" \
	"$(printf '%s\n' "$out" | awk 'NR==1 || prev=="---" {print} {prev=$0}' | paste -sd '|' -)"
has_line "update pulls the recorded image" "example.com/i:2" "$(printf '%s\n' "$out" | sed -n '1,/^---$/p')"
run_part=$(printf '%s\n' "$out" | sed -n '/^run$/,/^---$/p')
has_line "update keeps the name" "proj" "$run_part"
has_line "update keeps DIR" "$(cd "$T/my code" && pwd -P):/workspace" "$run_part"
has_line "update keeps the home volume" "h2:/home/agent" "$run_part"
has_line "update keeps the env file" "$envf" "$run_part"
has_line "update keeps the image last" "example.com/i:2" "$(printf '%s\n' "$run_part" | grep -v '^---$' | tail -1)"
case "$run_part" in
*no-new-privileges*) fail "update keeps --sudo" ;;
*) pass "update keeps --sudo" ;;
esac
printf '%s\n' "$p.dir=$T/my code" "$p.image=example.com/i:2" "$p.sudo=0" "$p.home=agentainer-home" "$p.env-file=" >"$T/labels/agentainer"
run_part=$(ins update 2>/dev/null | sed -n '/^run$/,$p')
has_line "update without --sudo keeps no-new-privileges" "no-new-privileges=true" "$run_part"
has_line "update defaults to the agentainer container" "agentainer" "$run_part"
: >"$T/labels/old"
assert_contains "update refuses a container without labels" "inspect it before recreating it" "$(ins update old 2>&1 || true)"
assert_eq "update without labels changes nothing" "" "$(ins update old 2>/dev/null || true)"
printf '%s\n' "$p.dir=$T/gone" "$p.image=example.com/i:2" "$p.sudo=0" "$p.home=h" "$p.env-file=" >"$T/labels/gone"
assert_contains "update with a missing DIR fails" "no longer exists" "$(ins update gone 2>&1 || true)"
assert_eq "update with a missing DIR changes nothing" "" "$(ins update gone 2>/dev/null || true)"
rc=0
out=$(ins update nosuch 2>/dev/null) || rc=$?
assert_eq "update of a missing container exits 1" "1" "$rc"
assert_eq "update of a missing container runs nothing" "" "$out"
# Every inspect call names --type container, so an image with the same name never answers.
calls=$(grep -c . "$T/labels.calls")
typed=$(grep -c -- ' --type container ' "$T/labels.calls")
if [ "$calls" -gt 0 ] && [ "$calls" = "$typed" ]; then pass "update inspects containers only"; else fail "update inspects containers only" "$typed of $calls inspect calls have --type container"; fi
printf '%s\n' "$p.dir=$T/my code" "$p.image=example.com/i:2" "$p.sudo=0" "$p.home=$T/here/home" "$p.env-file=" >"$T/labels/homedir"
has_line "update keeps a home directory" "$T/here/home:/home/agent" "$(cd / && ins update homedir 2>/dev/null)"
printf '%s\n' "$p.dir=$T/my code" "$p.image=example.com/i:2" "$p.sudo=0" "$p.home=$T/gone-home" "$p.env-file=" >"$T/labels/nohome"
assert_contains "update with a missing home directory fails" "home directory $T/gone-home, which no longer exists" "$(ins update nohome 2>&1 || true)"
assert_eq "update with a missing home directory changes nothing" "" "$(ins update nohome 2>/dev/null || true)"
printf '%s\n' "$p.dir=$T/my code" "$p.image=example.com/i:2" "$p.sudo=0" "$p.home=h" "$p.env-file=$T/moved-env" >"$T/labels/noenv"
assert_contains "update with a missing env file fails" "env file" "$(ins update noenv 2>&1 || true)"
assert_eq "update with a missing env file changes nothing" "" "$(ins update noenv 2>/dev/null || true)"
has_line "up records a relative env file as an absolute path" "io.github.chadmayfield.agentainer.env-file=$(cd "$T" && pwd -P)/env" \
	"$(cd "$T" && AGENTAINER_ENV_FILE="env" pod up "$T/my code" 2>/dev/null)"
assert_contains "usage lists start and update" "start [N] | update [N]" "$(sh "$L" 2>&1 || true)"
assert_eq "doctor runs diagnostics in the default container" "exec|agentainer|agentainer-doctor" "$(pod doctor | paste -sd '|' -)"
assert_eq "doctor forwards JSON mode without a TTY" "exec|agentainer|agentainer-doctor|--json" "$(pod doctor --json | paste -sd '|' -)"
assert_eq "doctor selects a named container" "exec|cx-project|agentainer-doctor|--json" "$(pod doctor cx-project --json | paste -sd '|' -)"
rc=0
out=$(pod doctor cx-project --json extra 2>&1) || rc=$?
assert_eq "doctor rejects extra arguments" 2 "$rc"

assert_contains "unknown command fails" "usage" "$(sh "$L" bogus 2>&1 || true)"
assert_contains "no runtime found is an error" "neither podman nor docker" "$(AGENTAINER_RUNTIME='' PATH=/nonexistent /bin/sh "$L" status 2>&1 || true)"

# up passes the host locale and time zone and records them in a label.
img=ghcr.io/chadmayfield/agentainer:latest
out=$(LANG=en_US.UTF-8 TZ=America/Denver pod up "$T/my code")
has_line "up passes locale variables with -e" "-e" "$out"
has_line "up passes LANG" "LANG=en_US.UTF-8" "$out"
has_line "up passes TZ" "TZ=America/Denver" "$out"
has_line "up records the locale" "$p.locale=LANG=en_US.UTF-8 TZ=America/Denver" "$out"
out=$(TZ=UTC LC_IDENTIFICATION=fr_FR.UTF-8 LC_TIME=de_DE.UTF-8 LC_ALL=en_GB.UTF-8 LC_CTYPE=en_US.UTF-8 LANG=en_US.UTF-8 pod up "$T/my code")
has_line "up records the locale in a fixed order" \
	"$p.locale=LANG=en_US.UTF-8 LC_ALL=en_GB.UTF-8 LC_CTYPE=en_US.UTF-8 LC_TIME=de_DE.UTF-8 LC_IDENTIFICATION=fr_FR.UTF-8 TZ=UTC" "$out"
ln -s /var/db/timezone/zoneinfo/Europe/Paris "$T/lt"
has_line "up takes TZ from the localtime link" "TZ=Europe/Paris" "$(AGENTAINER_LOCALTIME="$T/lt" pod up "$T/my code")"
assert_absent "no localtime link and no TZ pass no TZ" "$(pod up "$T/my code")" "$img" "TZ="
out=$(LC_CTYPE=UTF-8 LANG=en_US.ISO-8859-1 LC_TERMINAL=iTerm2 TZ=:/etc/localtime pod up "$T/my code")
assert_absent "invalid locale values are skipped" "$out" "$img" "LC_CTYPE=" "LANG=" "LC_TERMINAL=" "TZ="
assert_absent "a TZ with a space is skipped" "$(TZ='Bad Zone' AGENTAINER_LOCALTIME="$T/lt" pod up "$T/my code")" "$img" "TZ="
out=$(LANG=C.UTF-8 LC_TIME=en_US.utf8 LC_MESSAGES=sr_RS.UTF-8@latin LC_PAPER=ast_ES.UTF-8 pod up "$T/my code")
has_line "C.UTF-8 is accepted" "LANG=C.UTF-8" "$out"
has_line "a .utf8 codeset is accepted" "LC_TIME=en_US.utf8" "$out"
has_line "a modifier is accepted" "LC_MESSAGES=sr_RS.UTF-8@latin" "$out"
has_line "a three-letter language is accepted" "LC_PAPER=ast_ES.UTF-8" "$out"
assert_absent "a bad modifier is skipped" "$(LANG=en_US.UTF-8@ LC_TIME=de_DE.UTF-8@a-b pod up "$T/my code")" "$img" "LANG=" "LC_TIME="
# The env file wins over the host, and the launcher never prints its values.
printf '%s\n' "TZ=Asia/Tokyo" "# x" "LANG" "" "  SECRET_TOKEN=cx-secret-123" >"$T/env"
chmod 600 "$T/env"
out=$(AGENTAINER_ENV_FILE="$T/env" TZ=America/Denver LANG=en_US.UTF-8 LC_TIME=de_DE.UTF-8 pod up "$T/my code" 2>&1)
assert_absent "the env file wins over the host" "$out" "$img" "TZ=America/Denver" "LANG=en_US.UTF-8"
assert_absent "env file values are never printed" "$out" "$img" "cx-secret-123" "Asia/Tokyo"
has_line "variables the env file does not set still pass" "LC_TIME=de_DE.UTF-8" "$out"
has_line "the label records only what passed" "$p.locale=LC_TIME=de_DE.UTF-8" "$out"
# Docker strips a UTF-8 byte order mark before the first key, so the key still counts.
printf '\357\273\277%s\n' "TZ=Asia/Tokyo" >"$T/env"
out=$(AGENTAINER_ENV_FILE="$T/env" TZ=America/Denver pod up "$T/my code" 2>&1)
assert_absent "an env file with a byte order mark still wins" "$out" "$img" "TZ=America/Denver" "Asia/Tokyo"
printf '\357\273\277\t%s\n' "LANG=de_DE.UTF-8" >"$T/env"
out=$(AGENTAINER_ENV_FILE="$T/env" LANG=en_US.UTF-8 pod up "$T/my code" 2>&1)
assert_absent "a byte order mark before leading whitespace is stripped" "$out" "$img" "LANG=en_US.UTF-8" "de_DE"
printf '%s' "TZ=Asia/Tokyo" >"$T/env"
out=$(AGENTAINER_ENV_FILE="$T/env" TZ=America/Denver pod up "$T/my code" 2>&1)
assert_absent "a one-line env file without a newline still wins" "$out" "$img" "TZ=America/Denver"

finish
