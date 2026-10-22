#!/usr/bin/env python3
"""Install optional language servers in a disposable persistent home, then test offline."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
RUST_HOME = "/home/agent/.agentainer/rustup"
LEGACY_PROJECT = "/home/agent/.agentainer/typescript-legacy-fixture"
LEGACY_SERVER = LEGACY_PROJECT + "/node_modules/.bin/typescript-language-server"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", choices=("podman", "docker"), default=os.environ.get("RUNTIME", "podman"))
    parser.add_argument("--image", default=os.environ.get("IMAGE", "localhost/agentainer:dev"))
    args = parser.parse_args()
    token = "cx-language-" + uuid.uuid4().hex[:12]
    home = token + "-home"
    containers = []
    volume_created = False
    number = 0

    def command(*arguments, expected=0, timeout=900):
        result = subprocess.run([args.runtime, *arguments], capture_output=True, text=True, timeout=timeout)
        if result.returncode != expected:
            raise RuntimeError(f"{arguments[0]} exited {result.returncode}, expected {expected}\n"
                               + result.stdout[-6000:] + result.stderr[-6000:])
        return result.stdout

    def passed(message):
        nonlocal number
        number += 1
        print(f"ok {number} - {message}", flush=True)

    def start(suffix, offline=False):
        name = token + suffix
        containers.append(name)
        options = ["--network", "none", "-e", "RUSTUP_HOME=" + RUST_HOME] if offline else []
        command("run", "-d", "--rm", "--pull=never", "--name", name,
                "-v", home + ":/home/agent",
                "-v", str(ROOT / "tests/fixtures/check-language-servers.py") + ":/fixtures/check-language-servers.py:ro",
                "-e", "AGENTAINER_TOOLS=persist", "-e", "PYTHONDONTWRITEBYTECODE=1",
                *options, args.image, "sleep", "infinity")
        command("exec", "--user", "agent", name, "sh", "-ec",
                'i=0; until [ "$(readlink /var/lib/agentainer/active)" = "$HOME/.agentainer/tools" ]; do '
                'i=$((i+1)); [ "$i" -lt 60 ]; sleep 1; done')
        return name

    def execute(name, *arguments, expected=0):
        return command("exec", "--user", "agent", name, *arguments, expected=expected)

    def lsp(name, *arguments, expected=0):
        return execute(name, "env", "RUSTUP_HOME=" + RUST_HOME, "GOTOOLCHAIN=local", "GOPROXY=off",
                       "CARGO_NET_OFFLINE=true", "python3", "/fixtures/check-language-servers.py",
                       "--legacy-server", LEGACY_SERVER, *arguments, expected=expected)

    def inventory(name):
        return execute(name, "env", "RUSTUP_HOME=" + RUST_HOME, "python3", "-c",
                       "import hashlib,json,shutil,subprocess; from pathlib import Path; "
                       "paths={n:Path(shutil.which(n)).resolve() for n in "
                       "('gopls','pyright-langserver','tsc')}; "
                       "paths['typescript-legacy']=Path(" + repr(LEGACY_SERVER) + ").resolve(); "
                       "paths['rust-analyzer']=Path(subprocess.check_output(['rustup','which','rust-analyzer'],text=True).strip()); "
                       "print(json.dumps({n:hashlib.sha256(p.read_bytes()).hexdigest() for n,p in paths.items()},sort_keys=True))")

    try:
        command("volume", "create", home)
        volume_created = True
        name = start("-install")
        execute(name, "rustup", "toolchain", "install", "--help")
        execute(name, "rustup", "which", "--help")
        rust_version = execute(name, "rustc", "--version").split()[1]
        execute(name, "sh", "-ec", "command -v rust-analyzer >/dev/null; "
                "if rust-analyzer --version; then exit 1; fi")
        missing = execute(name, "python3", "/fixtures/check-language-servers.py", expected=1)
        if missing.count("not ok ") != 4 or "\nok " in missing:
            raise RuntimeError("Missing-server check failed for an unexpected reason\n" + missing)
        passed("all four LSP checks fail before installation, including the Rust proxy")
        print("# Installing gopls with the image's Go compiler", flush=True)
        execute(name, "env", "GOTOOLCHAIN=local", "go", "install", "golang.org/x/tools/gopls@latest")
        print("# Installing Pyright and TypeScript 7's native language server", flush=True)
        execute(name, "npm", "install", "--global", "pyright", "typescript@7")
        print("# Installing a project-local TypeScript 6 fallback", flush=True)
        # The legacy server's upstream installation instructions select compiler major 6.
        execute(name, "sh", "-ec", "mkdir -p " + LEGACY_PROJECT + "; cd " + LEGACY_PROJECT
                + "; npm init --yes; npm install --save-dev --save-exact typescript-language-server typescript@6")
        print("# Installing a user-owned Rust toolchain with rust-analyzer and rust-src", flush=True)
        execute(name, "env", "RUSTUP_HOME=" + RUST_HOME, "rustup", "toolchain", "install", rust_version,
                "--profile", "minimal", "--component", "rust-analyzer,rust-src", "--default", "--no-self-update")
        for arguments in (("gopls", "version"), ("pyright", "--version"), ("tsc", "--version"),
                          (LEGACY_SERVER, "--version")):
            print("# " + execute(name, *arguments).strip(), flush=True)
        print("# " + execute(name, "env", "RUSTUP_HOME=" + RUST_HOME, "rust-analyzer", "--version").strip(), flush=True)
        for line in lsp(name).splitlines():
            print("# " + line, flush=True)
        passed("all four language servers and the TypeScript 6 fallback return real document symbols")
        before = inventory(name)
        if len(json.loads(before)) != 5:
            raise RuntimeError("Incomplete language-server inventory")
        execute(name, "sh", "-ec", "mkdir /tmp/cx-fake-lsp; "
                "printf '#!/bin/sh\nexit 0\n' > /tmp/cx-fake-lsp/gopls; chmod 755 /tmp/cx-fake-lsp/gopls")
        negative = execute(name, "sh", "-ec",
                           'PATH="/tmp/cx-fake-lsp:$PATH" GOTOOLCHAIN=local '
                           'python3 /fixtures/check-language-servers.py --server go', expected=1)
        if not negative.startswith("not ok "):
            raise RuntimeError("Fake LSP process was not rejected")
        passed("a fake server that exits successfully fails the protocol check")
        command("stop", name)
        name = start("-offline", offline=True)
        if inventory(name) != before:
            raise RuntimeError("Language-server binaries changed across container recreation")
        for line in lsp(name).splitlines():
            print("# " + line, flush=True)
        passed("persisted servers work after container recreation with networking disabled")
        print(f"1..{number}", flush=True)
    finally:
        errors = []
        for name in reversed(containers):
            result = subprocess.run([args.runtime, "container", "inspect", name], capture_output=True)
            if result.returncode == 0:
                try:
                    command("rm", "-f", name)
                except Exception as error:
                    errors.append(str(error))
        if volume_created:
            try:
                command("volume", "rm", home)
            except Exception as error:
                errors.append(str(error))
        if errors:
            raise RuntimeError("Cleanup failed: " + "; ".join(errors))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("not ok - " + str(error), file=sys.stderr)
        raise SystemExit(1)
