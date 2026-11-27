"""Decide whether Docker and Podman leave a path out of a build context.

Python ports of the two ignore-file matchers, so a test can check what the
engines do with `.containerignore` and `Containerfile.dockerignore`:

- Docker (BuildKit): github.com/moby/patternmatcher at commit 5a6d842,
  `ignorefile.ReadAll` and `PatternMatcher.MatchesOrParentMatches`.
- Podman (Buildah): github.com/openshift/imagebuilder `ParseIgnoreReader` and
  github.com/containers/storage pkg/fileutils at commit 81c2f5f,
  `PatternMatcher.IsMatch`.

Both engines skip `#` comment lines, let `*` and `?` match within one path
segment only, let `**` span segments, and apply `!` lines in order, so the last
matching line decides.
"""
import posixpath
import re


def _clean(path):
    """Go's filepath.Clean for slash-separated paths."""
    if not path:
        return "."
    cleaned = posixpath.normpath(path)
    # normpath keeps a leading "//"; Go collapses it.
    return "/" + cleaned.lstrip("/") if cleaned.startswith("//") else cleaned


def _regex(pattern, docker):
    out = "^"
    i = 0
    escape = ".+()|{}$" if docker else ".$"
    while i < len(pattern):
        ch = pattern[i]
        i += 1
        if ch == "*":
            if i < len(pattern) and pattern[i] == "*":
                i += 1
                if i < len(pattern) and pattern[i] == "/":
                    i += 1
                out += ".*" if i == len(pattern) else "(.*/)?"
            else:
                out += "[^/]*"
        elif ch == "?":
            out += "[^/]"
        elif ch in escape:
            out += "\\" + ch
        elif ch == "\\":
            if i < len(pattern):
                out += "\\" + pattern[i]
                i += 1
            elif docker:
                out += "\\\\"
            else:
                raise ValueError("trailing backslash in " + repr(pattern))
        else:
            out += ch
    return re.compile(out + ("$" if docker else "(/.*)?$"))


def _docker_match(pattern, path):
    """moby Pattern.match, with its exact, prefix and suffix shortcuts."""
    if "**" in pattern and pattern.startswith("**"):
        suffix = pattern[2:]
        if not any(c in suffix for c in "*?[]\\"):
            return path.endswith(suffix) or (suffix.startswith("/") and path == suffix[1:])
    if not any(c in pattern for c in "*?[]\\"):
        return path == pattern
    if pattern.endswith("**") and not any(c in pattern[:-2] for c in "*?[]\\"):
        return path.startswith(pattern[:-2])
    return bool(_regex(pattern, docker=True).match(path))


def docker_patterns(text):
    """moby ignorefile.ReadAll followed by patternmatcher.New."""
    lines = text.splitlines()
    if lines and lines[0].startswith("﻿"):
        lines[0] = lines[0][1:]
    patterns = []
    for line in lines:
        if line.startswith("#"):
            continue
        line = line.strip()
        if not line:
            continue
        invert = line.startswith("!")
        if invert:
            line = line[1:].strip()
        if line:
            line = _clean(line)
            if len(line) > 1 and line.startswith("/"):
                line = line[1:]
        patterns.append((invert, _clean(line)))
    return patterns


def podman_patterns(text):
    """imagebuilder ParseIgnoreReader followed by fileutils.NewPatternMatcher."""
    patterns = []
    for line in text.split("\n"):
        if not line or line.startswith("#"):
            continue
        line = line.strip("/").strip()
        if not line:
            continue
        line = _clean(line)
        invert = line.startswith("!")
        if invert:
            line = _clean(line[1:]).removeprefix("/")
        patterns.append((invert, line))
    return patterns


def docker_excludes(text, path):
    excluded = False
    parents = posixpath.dirname(path).split("/")
    for invert, pattern in docker_patterns(text):
        if invert != excluded:
            continue
        match = _docker_match(pattern, path)
        if not match and posixpath.dirname(path):
            match = any(_docker_match(pattern, "/".join(parents[: i + 1])) for i in range(len(parents)))
        if match:
            excluded = not invert
    return excluded


def podman_excludes(text, path):
    excluded = False
    for invert, pattern in podman_patterns(text):
        if _regex(pattern, docker=False).match(path):
            excluded = not invert
    return excluded


def excluded_by_both(text, path):
    return docker_excludes(text, path) and podman_excludes(text, path)
