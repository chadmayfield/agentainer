"""Run diagnostics against real tools with networking disabled by the test runner."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

home = Path.home()
secret = "cx-doctor-private-value-never-print-this"


def require(condition, message="fixture condition failed"):
    if not condition:
        raise SystemExit(message)


def snapshot():
    return {str(path.relative_to(home)): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mode)
            for path in home.rglob("*") if path.is_file()}


def doctor(expected, env=None):
    before = snapshot()
    completed = subprocess.run(["agentainer-doctor", "--json"], capture_output=True, text=True,
                               env=env or dict(os.environ, OPENAI_API_KEY=secret), timeout=90)
    require(completed.returncode == expected, completed.stdout + completed.stderr)
    require(secret not in completed.stdout + completed.stderr, 'fixture condition failed')
    require(snapshot() == before, "diagnostics changed home files")
    return json.loads(completed.stdout)


report = doctor(0)
require(report["status"] == "ok", report)
require({"tool.claude", "tool.codex", "tool.agy", "tool.opencode", "home", "tools.persistence", "mcp"} <= {
    item["name"] for item in report["checks"]}, 'fixture condition failed')

settings = home / ".claude/settings.json"
original = settings.read_bytes()
try:
    settings.write_text('{"' + secret + '":')
    report = doctor(1)
    require(any(item["name"] == "config.claude" and item["status"] == "fail" for item in report["checks"]), 'fixture condition failed')
finally:
    settings.write_bytes(original)

box = home / ".agentainer"
source = box / "mcp.json"
source.write_text(json.dumps({"mcpServers": {"example": {"command": "echo", "args": [secret]}}}))
report = doctor(0)
require(any(item["name"] == "mcp" and item["status"] == "warn" for item in report["checks"]), 'fixture condition failed')
subprocess.run(["agentainer-mcp", "sync"], check=True, capture_output=True, text=True)
report = doctor(0)
require(any(item["name"] == "mcp" and item["status"] == "ok" for item in report["checks"]), 'fixture condition failed')

with tempfile.TemporaryDirectory(prefix="cx-doctor-tool-") as temporary:
    root = Path(temporary)
    record = root / "cx-environment.json"
    executable = root / "claude"
    executable.write_text("#!" + sys.executable + "\nimport json,os,sys\nfrom pathlib import Path\n"
                          + "Path(" + repr(str(record)) + ").write_text(json.dumps(dict(os.environ)))\n"
                          + "print(" + repr(secret) + ")\nprint(" + repr(secret) + ",file=sys.stderr)\nsys.exit(1)\n")
    executable.chmod(0o755)
    report = doctor(1, dict(os.environ, PATH=str(root) + ":" + os.environ["PATH"], OPENAI_API_KEY=secret))
    require(any(item["name"] == "tool.claude" and item["status"] == "fail" for item in report["checks"]), 'fixture condition failed')
    environment = json.loads(record.read_text())
    require(secret not in json.dumps(environment), 'fixture condition failed')
    require(environment["HOME"] != str(home), 'fixture condition failed')
    require(not Path(environment["HOME"]).exists(), "version probe temporary home was not removed")

print("DOCTOR_VERIFIED")
