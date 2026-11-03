#!/bin/sh
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"

# assert_match NAME REGEX OUTPUT: passes when OUTPUT matches the extended REGEX.
assert_match() {
	if printf '%s\n' "$3" | grep -Eq "$2"; then pass "$1"; else fail "$1" "[$2] does not match [$3]"; fi
}

locales=$(run_in --network none -- locale -a 2>&1)
assert_contains "en_US locale installed" en_US.utf8 "$locales"
assert_contains "de_DE locale installed" de_DE.utf8 "$locales"

# shellcheck disable=SC2016 # expands in the container
assert_eq "default LANG stays C.UTF-8" C.UTF-8 "$(run_in --network none -- sh -c 'printf %s "$LANG"')"

# tmux formats %x through strftime, so it follows LC_TIME. The date command is
# not used: Ubuntu's date is uutils and ignores the locale.
tmux_date='tmux -L t -f /dev/null new-session -d \; display-message -p "%x" \; kill-server'
de=$(run_in --network none -e LC_TIME=de_DE.UTF-8 -- sh -c "$tmux_date" 2>&1)
assert_match "tmux %x follows LC_TIME=de_DE" '^[0-9]{2}\.[0-9]{2}\.[0-9]{4}$' "$de"

# en_PH has the widest %x of the installed locales; the status bar is sized for it.
width=$(run_in --network none -e LC_TIME=en_PH.UTF-8 -- python3 -c "import locale,datetime; locale.setlocale(locale.LC_TIME,''); print(len(datetime.date(2027,9,29).strftime('%x')))" 2>&1)
assert_eq "widest %x is 29 characters (en_PH)" 29 "$width"

# A locale the image lacks falls back to the C format and the shell still starts.
missing=$(run_in --network none -e LANG=en_DE.UTF-8 -e LC_TIME=en_DE.UTF-8 -- bash -lc "echo cx-shell-ok; $tmux_date" 2>&1)
assert_contains "shell starts with a missing locale" cx-shell-ok "$missing"
assert_match "tmux %x falls back to the C format" '^[0-9]{2}/[0-9]{2}/[0-9]{2}$' "$missing"

finish
