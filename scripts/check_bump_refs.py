#!/usr/bin/env python3
"""Refuse a version bump that changes more than version references in a file.

  check_bump_refs.py NEW.env PATH...

Run in the checkout after the bump patch is applied. For each PATH, the text in HEAD
and the text in the work tree must be the same after every version reference and every
digest-pinned image reference is replaced with a placeholder. Each reference that
changed must then hold the new pin from NEW.env: AGENTAINER_RELEASE_VERSION for a
release reference, the extra's *_VERSION for an extras reference and a *_IMAGE value for
an image reference. Prints each problem and exits 1.

.github/actions/bump-pr/action.yml runs the copy of this script from the commit before
the patch, for the files that repeat a pin (RELEASE_REFS, K8S_IMAGES and EXTRAS_DOC in
scripts/bump_versions.py). tests/unit/test_bump_workflow.py checks that PREFIXES,
EXTRA_PACKAGES and EXTRA_SEPARATORS match scripts/bump_versions.py.
"""
import re
import subprocess
import sys

# The text before a release version in each RELEASE_REFS entry.
PREFIXES = ("ghcr.io/chadmayfield/agentainer:", "newTag: ", "version=")
# A SemVer version, as AGENTAINER_RELEASE_VERSION holds.
SEMVER = r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
RELEASE = re.compile("(%s)(%s)" % ("|".join(re.escape(p) for p in PREFIXES), SEMVER))
# The extras pins and their npm packages (EXTRAS in scripts/bump_versions.py), and the text
# between a package name and its version in docs/extras.md (EXTRAS_DOC_SEPARATORS).
EXTRA_PACKAGES = (("KANDEV_VERSION", "kandev"), ("OPENCHAMBER_VERSION", "@openchamber/web"),
                  ("REA_VERSION", "rea-agents"))
EXTRA_SEPARATORS = (" ", "` ", "@", "/")
# Each version reference pattern, with the versions.env key a changed reference must hold.
VERSION_REFS = [(RELEASE, "AGENTAINER_RELEASE_VERSION")] + [
    (re.compile(r"(?<![A-Za-z0-9._-])(%s)(%s)" % ("|".join(re.escape(package + sep) for sep in EXTRA_SEPARATORS),
                                                  SEMVER)), key)
    for key, package in EXTRA_PACKAGES]
# A Docker Hub reference as bump_versions.hub_ref writes it. The repository stays part of
# the text; only the tag and digest may change.
IMAGE = re.compile(r"(docker\.io/[a-z0-9._/-]+):([A-Za-z0-9._-]+@sha256:[0-9a-f]{64})")


def read_env(path):
    values = {}
    with open(path) as f:
        for line in f:
            m = re.match(r"([A-Z0-9_]+)=(.*)$", line.rstrip("\n"))
            if m:
                values[m.group(1)] = m.group(2)
    return values


def normalize(line):
    for pattern, key in VERSION_REFS:
        line = pattern.sub(r"\1<%s>" % key, line)
    return IMAGE.sub(r"\1:<image>", line)


def problems(rel, old, new, env):
    """Problems with the change from old to new text in rel, as "rel:line: why" strings."""
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    if len(old_lines) != len(new_lines):
        return ["%s: adds or removes lines" % rel]
    images = {v for k, v in env.items() if k.endswith("_IMAGE")}
    found = []
    for n, (a, b) in enumerate(zip(old_lines, new_lines), 1):
        if a == b:
            continue
        if normalize(a) != normalize(b):
            found.append("%s:%d: changes more than a version reference: %r" % (rel, n, b))
            continue
        for pattern, key in VERSION_REFS:
            for x, y in zip(pattern.finditer(a), pattern.finditer(b)):
                if x.group(0) != y.group(0) and y.group(2) != env.get(key):
                    found.append("%s:%d: %s is not %s (%s)" % (rel, n, y.group(0), key, env.get(key)))
        for x, y in zip(IMAGE.finditer(a), IMAGE.finditer(b)):
            if x.group(0) != y.group(0) and y.group(0) not in images:
                found.append("%s:%d: %s is not an image pin in versions.env" % (rel, n, y.group(0)))
    return found


def main(argv):
    if len(argv) < 2:
        print("usage: check_bump_refs.py NEW.env PATH...", file=sys.stderr)
        return 2
    env = read_env(argv[0])
    found = []
    for rel in argv[1:]:
        old = subprocess.run(["git", "show", "HEAD:" + rel], capture_output=True, text=True, check=True).stdout
        with open(rel) as f:
            new = f.read()
        found += problems(rel, old, new, env)
    for line in found:
        print(line)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
