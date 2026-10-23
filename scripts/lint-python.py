#!/usr/bin/env python3
"""Run Ruff over Python sources, including commands without a .py suffix."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ("bin", "build", "scripts", "tests", "deploy", "rootfs", ".github")
SKIP_DIRS = {"node_modules", "__pycache__", ".venv"}


def python_files(root):
    files = []
    for directory in SOURCE_DIRS:
        for path in (root / directory).rglob("*"):
            if not path.is_file() or SKIP_DIRS.intersection(path.relative_to(root).parts):
                continue
            if path.suffix == ".py":
                files.append(str(path.relative_to(root)))
                continue
            with path.open("rb") as source:
                first = source.readline(256)
            if first.startswith(b"#!") and b"python" in first:
                files.append(str(path.relative_to(root)))
    return sorted(files)


def main():
    files = python_files(ROOT)
    if not files:
        print("No Python sources found", file=sys.stderr)
        return 1
    # Explicit paths include build/ and extensionless commands that default discovery omits.
    # https://docs.astral.sh/ruff/configuration/#python-file-discovery
    return subprocess.run(["ruff", "check", "--no-cache", "--config", "ruff.toml", "--", *files],
                          cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
