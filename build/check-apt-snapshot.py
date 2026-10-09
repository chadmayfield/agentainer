"""Fails the build unless every installed package version is available from the snapshot.

Runs after the snapshot install, before the apt lists are removed. Writes the
mismatches (one "package version" per line) to the file named on the command line,
so tests can show the file is empty.
"""
import re
import subprocess
import sys

out_path = sys.argv[1]
pkgs = subprocess.check_output(["dpkg-query", "-W", "-f", "${Package}\n"], universal_newlines=True).split()
policy = subprocess.check_output(["apt-cache", "policy"] + pkgs, universal_newlines=True)

bad = []
for block in re.split(r"\n(?=\S)", policy):
    name = block.split(":", 1)[0].strip()
    installed = re.search(r"^\s+Installed: (\S+)", block, re.M)
    if not installed:
        continue
    version = installed.group(1)
    sources = []
    current = False
    for line in block.splitlines():
        v = re.match(r"^ (?:\*\*\*|   ) (\S+) \d+$", line)
        if v:
            current = v.group(1) == version
            continue
        s = re.match(r"^\s+\d+ (\S+)", line)
        if s and current:
            sources.append(s.group(1))
    if not any("snapshot.ubuntu.com" in s for s in sources):
        bad.append("%s %s" % (name, version))

with open(out_path, "w") as f:
    f.write("".join(b + "\n" for b in bad))
if bad:
    print("check-apt-snapshot: not from the snapshot:\n  " + "\n  ".join(bad), file=sys.stderr)
    sys.exit(1)
