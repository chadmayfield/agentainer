"""Container-tag-compatible SemVer and Agentainer default upgrade policy.

Ordering follows https://semver.org/#spec-item-11. Build metadata is excluded
because container tags cannot contain '+'. Dated development builds use
MAJOR.MINOR.PATCH-dev.YYYYMMDD.N, with a real date and positive build number.
"""
import datetime
from pathlib import Path
import re
import sys

NUMBER = r"(?:0|[1-9][0-9]*)"
VERSION = re.compile(r"(" + NUMBER + r")\.(" + NUMBER + r")\.(" + NUMBER +
                     r")(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?")


def version_key(value):
    match = VERSION.fullmatch(value)
    if not match or len(value) > 128:
        raise ValueError("invalid release version %r" % value)
    pre = match.group(4)
    identifiers = () if pre is None else tuple(pre.split("."))
    if any(part.isdigit() and len(part) > 1 and part.startswith("0") for part in identifiers):
        raise ValueError("leading zero in prerelease %r" % value)
    if identifiers and identifiers[0] == "dev":
        if (len(identifiers) != 3 or not re.fullmatch(r"[0-9]{8}", identifiers[1])
                or not re.fullmatch(r"[1-9][0-9]*", identifiers[2])):
            raise ValueError("expected dev.YYYYMMDD.N in %r" % value)
        date = identifiers[1]
        datetime.date(int(date[:4]), int(date[4:6]), int(date[6:]))
    order = tuple((0, int(part)) if part.isdigit() else (1, part) for part in identifiers)
    return tuple(map(int, match.group(1, 2, 3))) + (int(pre is None), order)


def from_merge(subject, owner):
    match = re.fullmatch(r"Merge pull request #[0-9]+ from " + re.escape(owner) +
                         r"/release/(.+)", subject.rstrip("\n"))
    if not match:
        raise ValueError("expected a release pull request merge from %s" % owner)
    value = match.group(1)
    version_key(value)
    return value


def newer_default(candidate, current_hash, ledger):
    try:
        requested = version_key(candidate)
    except ValueError:
        return False
    recorded = []
    known = False
    for line in Path(ledger).read_text().splitlines():
        fields = line.split()
        if not fields or fields[0] != current_hash:
            continue
        known = True
        if len(fields) == 2:
            try:
                recorded.append(version_key(fields[1]))
            except ValueError:
                pass
    if not known:
        return False
    # A prerelease never replaces a default associated with a stable release,
    # including when that prerelease targets a higher major or minor version.
    if requested[3] == 0 and any(key[3] == 1 for key in recorded):
        return False
    return not recorded or requested > max(recorded)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) == 2 and args[0] == "from-merge":
            print(from_merge(sys.stdin.read(), args[1]))
        elif len(args) == 2 and args[0] == "prerelease":
            print("true" if version_key(args[1])[3] == 0 else "false")
        elif len(args) == 4 and args[0] == "newer-default":
            return 0 if newer_default(*args[1:]) else 1
        else:
            print("usage: release_version.py from-merge OWNER | prerelease VERSION | "
                  "newer-default VERSION HASH LEDGER", file=sys.stderr)
            return 2
    except (ValueError, OSError) as error:
        print("release_version: %s" % error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
