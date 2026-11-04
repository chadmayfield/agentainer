#!/usr/bin/env python3
"""Networked optional setup check. Use disposable homes, workspaces and containers."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]

# Pinned so the check does not change under a new release. The plugin runs @latest.
MCP_VERSION = "0.0.84"

# Runs inside the container as the agent user. Starts the server over stdio, lists the
# tools, opens a page served on 127.0.0.1 and takes a screenshot.
MCP_CHECK = r"""
import base64, json, subprocess, sys
site = subprocess.Popen(["python3", "-m", "http.server", "8765", "--bind", "127.0.0.1",
                         "--directory", "/tmp/mcp-site"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
server = subprocess.Popen(["npx", "-y", "@playwright/mcp@" + sys.argv[1]], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, text=True)
def send(message):
    server.stdin.write(json.dumps({"jsonrpc": "2.0", **message}) + "\n")
    server.stdin.flush()
def call(number, method, params):
    send({"id": number, "method": method, "params": params})
    while True:
        line = server.stdout.readline()
        if not line:
            raise SystemExit("MCP server closed its output")
        reply = json.loads(line)
        if reply.get("id") == number:
            if "error" in reply or reply["result"].get("isError"):
                raise SystemExit("MCP error: " + json.dumps(reply)[:2000])
            return reply["result"]
try:
    call(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "agentainer-test", "version": "0"}})
    send({"method": "notifications/initialized"})
    names = {tool["name"] for tool in call(2, "tools/list", {})["tools"]}
    assert {"browser_navigate", "browser_take_screenshot"} <= names, sorted(names)
    page = call(3, "tools/call", {"name": "browser_navigate", "arguments": {"url": "http://127.0.0.1:8765/"}})
    assert "http://127.0.0.1:8765/" in json.dumps(page), page
    shot = call(4, "tools/call", {"name": "browser_take_screenshot", "arguments": {}})
    images = [part for part in shot["content"] if part["type"] == "image"]
    assert len(images) == 1, shot
    assert base64.b64decode(images[0]["data"]).startswith(bytes.fromhex("89504e470d0a1a0a"))
    print("mcp-ok tools=%d" % len(names))
finally:
    server.terminate()
    site.terminate()
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", choices=("podman", "docker"), default=os.environ.get("RUNTIME", "podman"))
    parser.add_argument("--image", default=os.environ.get("IMAGE", "localhost/agentainer:dev"))
    args = parser.parse_args()
    token = "cx-playwright-" + uuid.uuid4().hex[:12]
    home, workspace = token + "-home", token + "-workspace"
    containers, volumes = [], []
    number = 0

    def command(*arguments, expected=0, timeout=600):
        result = subprocess.run([args.runtime, *arguments], capture_output=True, text=True, timeout=timeout)
        if result.returncode != expected:
            raise RuntimeError(f"{arguments[0]} exited {result.returncode}, expected {expected}\n"
                               + result.stdout[-4000:] + result.stderr[-4000:])
        return result.stdout

    def passed(message):
        nonlocal number
        number += 1
        print(f"ok {number} - {message}", flush=True)

    def start(suffix):
        name = token + suffix
        containers.append(name)
        command("run", "-d", "--rm", "--pull=never", "--name", name,
                "-v", home + ":/home/agent", "-v", workspace + ":/workspace",
                "-v", str(ROOT / "tests/fixtures/browser-smoke.spec.cjs") + ":/fixtures/browser-smoke.spec.cjs:ro",
                "-w", "/workspace",
                "-e", "PLAYWRIGHT_BROWSERS_PATH=/home/agent/.cache/ms-playwright",
                "-e", "PYTHONDONTWRITEBYTECODE=1", "--security-opt", "no-new-privileges", args.image, "sleep", "infinity")
        command("exec", "--user", "root", name, "chown", "agent:agent", "/workspace")
        # The entrypoint and exec can run concurrently after a detached start.
        command("exec", "--user", "agent", name, "sh", "-ec",
                "i=0; until [ -L /var/lib/agentainer/active ] && [ -f /home/agent/.agentainer/image-version ]; do "
                'i=$((i+1)); [ "$i" -lt 60 ]; sleep 1; done')
        return name

    def execute(name, *arguments, expected=0):
        return command("exec", "--user", "agent", name, *arguments, expected=expected)

    def browser_inventory(name):
        return execute(name, "python3", "-c",
                       "from pathlib import Path; import hashlib,json; "
                       "root=Path.home()/'.cache/ms-playwright'; "
                       "print(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() "
                       "for p in root.rglob('*') if p.is_file() and '.links' not in p.parts},sort_keys=True))")

    def smoke(name):
        execute(name, "./node_modules/.bin/playwright", "test", "browser-smoke.spec.cjs", "--workers=1", "--reporter=line")
        execute(name, "python3", "-c",
                "from pathlib import Path; "
                "files=list(Path('test-results').rglob('browser-smoke.png')); "
                "assert len(files)==1, files; "
                "assert files[0].read_bytes().startswith(bytes.fromhex('89504e470d0a1a0a'))")

    try:
        for volume in (home, workspace):
            command("volume", "create", volume)
            volumes.append(volume)
        name = start("-install")
        version = json.loads((ROOT / "tests/visual/package.json").read_text())["devDependencies"]["@playwright/test"]
        execute(name, "npm", "init", "--yes")
        execute(name, "npm", "install", "--save-dev", "--save-exact", "@playwright/test@" + version)
        execute(name, "cp", "/fixtures/browser-smoke.spec.cjs", "/workspace/browser-smoke.spec.cjs")
        missing = execute(name, "./node_modules/.bin/playwright", "test", "browser-smoke.spec.cjs",
                          "--workers=1", "--reporter=line", expected=1)
        if "Executable doesn't exist" not in missing:
            raise RuntimeError("Missing-browser check failed for an unexpected reason\n" + missing[-4000:])
        passed("browser test fails before browser installation")
        execute(name, "./node_modules/.bin/playwright", "install", "--help")
        execute(name, "./node_modules/.bin/playwright", "install", "--only-shell", "chromium")
        smoke(name)
        passed("headless Chromium renders, clicks and writes a PNG without root")
        before = browser_inventory(name)
        if not json.loads(before):
            raise RuntimeError("No browser files in the persistent home")
        execute(name, "sh", "-ec", "printf '\n' >> browser-smoke.spec.cjs; "
                "printf \"test('deliberate failure', () => { expect(1).toBe(2); });\\n\" >> browser-smoke.spec.cjs")
        execute(name, "./node_modules/.bin/playwright", "test", "browser-smoke.spec.cjs",
                "--workers=1", "--reporter=line", expected=1)
        execute(name, "cp", "/fixtures/browser-smoke.spec.cjs", "/workspace/browser-smoke.spec.cjs")
        passed("a deliberately wrong assertion fails the test run")
        command("stop", name)
        name = start("-recreated")
        if browser_inventory(name) != before:
            raise RuntimeError("Browser files changed across container recreation")
        passed("browser files survive container recreation with identical hashes")
        smoke(name)
        if browser_inventory(name) != before:
            raise RuntimeError("The second run changed the installed browser files")
        passed("recreated container uses persisted browsers without any dependency setup")
        # The MCP server downloads its own browser build into the same cache, so this
        # runs last. The project's browser files must stay unchanged next to it.
        execute(name, "sh", "-ec", "mkdir -p /tmp/mcp-site && echo '<h1>mcp-ok</h1>' > /tmp/mcp-site/index.html")
        execute(name, "npx", "-y", "@playwright/mcp@" + MCP_VERSION, "install-browser", "chromium")
        report = execute(name, "python3", "-c", MCP_CHECK, MCP_VERSION)
        if "mcp-ok" not in report:
            raise RuntimeError("MCP check printed no success marker\n" + report[-4000:])
        after = json.loads(browser_inventory(name))
        if not all(after.get(path) == digest for path, digest in json.loads(before).items()):
            raise RuntimeError("The MCP browser install changed the project's browser files")
        if len(after) <= len(json.loads(before)):
            raise RuntimeError("The MCP browser install added no browser files")
        passed("Playwright MCP server lists tools, opens a local page and takes a screenshot")
        print(f"1..{number}", flush=True)
    finally:
        cleanup_errors = []
        for name in reversed(containers):
            result = subprocess.run([args.runtime, "container", "exists", name], capture_output=True) if args.runtime == "podman" else subprocess.run(
                [args.runtime, "container", "inspect", name], capture_output=True)
            if result.returncode == 0:
                try:
                    command("rm", "-f", name)
                except Exception as error:
                    cleanup_errors.append(str(error))
        for volume in reversed(volumes):
            try:
                command("volume", "rm", volume)
            except Exception as error:
                cleanup_errors.append(str(error))
        if cleanup_errors:
            raise RuntimeError("Cleanup failed: " + "; ".join(cleanup_errors))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("not ok - " + str(error), file=sys.stderr)
        raise SystemExit(1)
