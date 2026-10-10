"""Fails the build unless every installed package version is available from the snapshot.

Runs after the snapshot install, before the apt lists are removed. Writes the
mismatches (one "package version" per line) to the file named on the command line,
so tests can show the file is empty.
"""
import re
import subprocess
import sys

# Version-table lines look like " *** 1.2 500" or "     1.2 500 (phased 15%)".
VERSION_LINE = re.compile(r"^ (?:\*\*\*|   ) (\S+) -?\d+(?: .*)?$")
SOURCE_LINE = re.compile(r"^\s+-?\d+ (\S+)")


def unpinned(policy):
    """Return "name version" for each installed version not offered by the snapshot."""
    bad = []
    for block in re.split(r"\n(?=\S)", policy):
        name = block.split(":", 1)[0].strip()
        installed = re.search(r"^\s+Installed: (\S+)", block, re.M)
        if not installed or installed.group(1) == "(none)":
            continue
        version = installed.group(1)
        sources = []
        current = False
        for line in block.splitlines():
            v = VERSION_LINE.match(line)
            if v:
                current = v.group(1) == version
                continue
            s = SOURCE_LINE.match(line)
            if s and current:
                sources.append(s.group(1))
        if not any("snapshot.ubuntu.com" in s for s in sources):
            bad.append("%s %s" % (name, version))
    return bad


def main(out_path):
    pkgs = subprocess.check_output(["dpkg-query", "-W", "-f", "${Package}\n"], universal_newlines=True).split()
    bad = unpinned(subprocess.check_output(["apt-cache", "policy"] + pkgs, universal_newlines=True))
    with open(out_path, "w") as f:
        f.write("".join(b + "\n" for b in bad))
    if bad:
        print("check-apt-snapshot: not from the snapshot:\n  " + "\n  ".join(bad), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
