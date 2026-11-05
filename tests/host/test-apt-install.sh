#!/bin/sh
# Host-side tests for build/apt-install.sh. Stub apt-get, apt-cache, dpkg and python3 on PATH
# log every call, and APT_INSTALL_ROOT points the script at a scratch tree, so no package is
# installed. STUB_SNAPSHOT_DOWN=1 makes apt-get update fail while the sources carry a Snapshot:
# field. STUB_CHECK_RC is the exit status of check-apt-snapshot.py.
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/../lib.sh"
S="$(cd "$(dirname "$0")/../.." && pwd)/build/apt-install.sh"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
trap 'exit 130' INT TERM
mkdir "$T/bin"
cat >"$T/bin/apt-get" <<'STUB'
#!/bin/sh
if grep -q '^Snapshot:' "$APT_INSTALL_ROOT/etc/apt/sources.list.d/ubuntu.sources"; then src=snapshot; else src=archive; fi
echo "apt-get $* [sources=$src]" >>"$STUB_LOG"
case " $* " in
*" --fix-broken "*)
	[ "${STUB_FIXBROKEN_RC:-0}" = 0 ] || echo "E: fix-broken failed" >&2
	exit "${STUB_FIXBROKEN_RC:-0}"
	;;
esac
case " $* " in
*" update "*)
	if [ "${STUB_SNAPSHOT_DOWN:-0}" = 1 ] && grep -q '^Snapshot:' "$APT_INSTALL_ROOT/etc/apt/sources.list.d/ubuntu.sources"; then
		echo "E: Failed to fetch the snapshot" >&2
		exit 100
	fi
	;;
esac
exit 0
STUB
cat >"$T/bin/apt-cache" <<'STUB'
#!/bin/sh
echo "apt-cache $*" >>"$STUB_LOG"
echo "bash policy"
STUB
cat >"$T/bin/dpkg" <<'STUB'
#!/bin/sh
echo "dpkg $*" >>"$STUB_LOG"
STUB
cat >"$T/bin/python3" <<'STUB'
#!/bin/sh
echo "python3 $*" >>"$STUB_LOG"
: >"$2"
exit "${STUB_CHECK_RC:-0}"
STUB
chmod +x "$T/bin/"*

# run_script [ENV=VALUE ...]: runs the script in a fresh tree; sets rc, LOG and ROOT.
run_script() {
	ROOT=$T/root
	LOG=$T/log
	rm -rf "$ROOT" "$LOG"
	mkdir -p "$ROOT/etc/apt/sources.list.d" "$ROOT/usr/local/share/agentainer" "$ROOT/var/lib/apt/lists" \
		"$ROOT/var/log/apt" "$ROOT/tmp/agentainer-build"
	echo git >"$ROOT/tmp/agentainer-build/apt-packages.txt"
	: >"$LOG"
	env "$@" PATH="$T/bin:$PATH" STUB_LOG="$LOG" APT_INSTALL_ROOT="$ROOT" APT_SNAPSHOT=20261104T000000Z \
		sh "$S" >"$T/out" 2>"$T/err"
	rc=$?
}
log_line() { grep -n -- "$1" "$LOG" | sed -n "${2:-1}p" | cut -d: -f1; }

run_script APT_FALLBACK=archive
assert_eq "snapshot success exits 0" 0 "$rc"
assert_eq "snapshot success records the snapshot" "snapshot 20261104T000000Z" "$(cat "$ROOT/usr/local/share/agentainer/apt-source")"
assert_absent "snapshot success runs no dpkg recovery" "$(
	cat "$LOG"
	echo LOG_READ
)" "LOG_READ" "dpkg --configure"
assert_absent "snapshot success leaves no Snapshot: field" "$(
	cat "$ROOT/etc/apt/sources.list.d/ubuntu.sources"
	echo SOURCES_READ
)" "SOURCES_READ" "Snapshot:"

# The snapshot is unreachable.
run_script APT_FALLBACK=archive STUB_SNAPSHOT_DOWN=1
assert_eq "fallback exits 0" 0 "$rc"
assert_contains "fallback records the date" "archive-fallback " "$(cat "$ROOT/usr/local/share/agentainer/apt-source")"
assert_contains "fallback warns on stderr" "WARNING" "$(cat "$T/err")"
assert_absent "fallback sources carry no Snapshot: field" "$(
	cat "$ROOT/etc/apt/sources.list.d/ubuntu.sources"
	echo SOURCES_READ
)" "SOURCES_READ" "Snapshot:"
# Recovery commands run between the failed attempt and the archive retry (dpkg(1) --configure -a;
# apt-get(8) --fix-broken).
first_fail=$(log_line "apt-get .*update" 1)
second_update=$(log_line "apt-get .*update" 2)
configure=$(log_line "dpkg --configure -a")
fix=$(log_line "apt-get .*--fix-broken")
assert_eq "dpkg --configure -a runs before the archive update" yes \
	"$([ -n "$configure" ] && [ "$configure" -gt "$first_fail" ] && [ "$configure" -lt "$second_update" ] && echo yes)"
assert_eq "apt-get --fix-broken install runs after the archive update" yes \
	"$([ -n "$fix" ] && [ "$fix" -gt "$second_update" ] && echo yes)"
assert_contains "the archive update runs with the archive sources" "update --error-on=any [sources=archive]" \
	"$(sed -n "${second_update}p" "$LOG")"
assert_contains "apt-get --fix-broken install runs with the archive sources" "[sources=archive]" "$(sed -n "${fix}p" "$LOG")"
first_install=$(log_line "apt-get .* install -y --no-install-recommends")
assert_eq "the package install runs after --fix-broken" yes \
	"$([ -n "$first_install" ] && [ "$first_install" -gt "$fix" ] && echo yes)"
run_script APT_FALLBACK=archive STUB_SNAPSHOT_DOWN=1 STUB_FIXBROKEN_RC=100
assert_eq "a --fix-broken failure fails the fallback" yes "$([ "$rc" -ne 0 ] && echo yes)"
assert_absent "a --fix-broken failure writes no apt-source" "$(
	ls "$ROOT/usr/local/share/agentainer"
	echo LS_READ
)" "LS_READ" "apt-source"

run_script STUB_SNAPSHOT_DOWN=1
assert_eq "strict exits 1" 1 "$rc"
assert_absent "strict writes no apt-source" "$(
	ls "$ROOT/usr/local/share/agentainer"
	echo LS_READ
)" "LS_READ" "apt-source"
run_script APT_FALLBACK=other STUB_SNAPSHOT_DOWN=1
assert_eq "a value other than archive is strict" 1 "$rc"

# A version outside the snapshot makes check-apt-snapshot.py fail after a successful install.
run_script APT_FALLBACK=archive STUB_CHECK_RC=1
assert_eq "a failed snapshot check falls back" 0 "$rc"
assert_contains "a failed snapshot check records the fallback" "archive-fallback " "$(cat "$ROOT/usr/local/share/agentainer/apt-source")"
run_script STUB_CHECK_RC=1
assert_eq "a failed snapshot check fails a strict build" 1 "$rc"
assert_absent "a failed strict check writes no apt-source" "$(
	ls "$ROOT/usr/local/share/agentainer"
	echo LS_READ
)" "LS_READ" "apt-source"
finish
