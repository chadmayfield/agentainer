#!/usr/bin/env python3
"""Print whether VERSION may move latest, using main's first-parent subjects on stdin."""
import datetime
import re
import sys

VERSION = r"([0-9]{4})\.([0-9]{2})\.([0-9]{2})(?:\.([1-9][0-9]*))?"


def version_key(value):
    m = re.fullmatch(VERSION, value)
    if not m:
        raise ValueError("invalid release version %r" % value)
    year, month, day = map(int, m.group(1, 2, 3))
    datetime.date(year, month, day)
    return year, month, day, int(m.group(4) or 0)


def may_move_latest(candidate, owner, subjects):
    requested = version_key(candidate)
    pattern = re.compile(r"^Merge pull request #[0-9]+ from " + re.escape(owner) + r"/release/(.+)$")
    releases = []
    for subject in subjects:
        m = pattern.fullmatch(subject.rstrip("\n"))
        if m:
            releases.append(version_key(m.group(1)))
    if requested not in releases:
        raise ValueError("release %s is not in main's release history" % candidate)
    return requested == max(releases)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("usage: release_order.py VERSION OWNER", file=sys.stderr)
        return 2
    try:
        allowed = may_move_latest(argv[0], argv[1], sys.stdin)
    except ValueError as e:
        print("release_order: %s" % e, file=sys.stderr)
        return 1
    print("true" if allowed else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
