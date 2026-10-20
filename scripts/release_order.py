#!/usr/bin/env python3
"""Print whether VERSION may move latest, using main's first-parent subjects on stdin."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rootfs/usr/local/lib/agentainer"))
from release_version import from_merge, version_key


def may_move_latest(candidate, owner, subjects):
    requested = version_key(candidate)
    releases = []
    for subject in subjects:
        try:
            releases.append(version_key(from_merge(subject, owner)))
        except ValueError:
            # Rejected merge subjects are not releases.
            continue
    if requested not in releases:
        raise ValueError("release %s is not in main's release history" % candidate)
    stable = [key for key in releases if key[3] == 1]
    return requested[3] == 1 and requested == max(stable)


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
