"""Run the AGENTS.md entrypoint step against isolated shared-home fixtures."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "rootfs/usr/local/lib/agentainer/release_version.py"
# The entrypoint's home_path helper, which the step calls.
HOME_PATH = re.search(r"^home_path\(\) \{\n.*?^\}\n",
                      (ROOT / "rootfs/usr/local/bin/agentainer-entrypoint").read_text(), re.S | re.M).group(0)


@unittest.skipUnless(shutil.which("flock"), "entrypoint requires Linux flock")
class AgentsVersionTests(unittest.TestCase):
    def apply(self, candidate, records, edited=False):
        with tempfile.TemporaryDirectory(prefix="cx-agents-version-") as d:
            base = Path(d)
            home, image = base / "home", base / "image"
            canon = home / ".agentainer/AGENTS.md"
            canon.parent.mkdir(parents=True)
            old = "old default\n"
            canon.write_text(old + ("user edit\n" if edited else ""))
            canon.chmod(0o600)
            digest = hashlib.sha256(old.encode()).hexdigest()
            ledger = canon.parent / "agents-default.sha256"
            ledger.write_text("".join(digest + " " + value + "\n" for value in records))
            image.mkdir()
            (image / "AGENTS.md").write_text("new default\n")
            source = (ROOT / "rootfs/usr/local/lib/agentainer/entrypoint.d/30-agents-md.sh").read_text()
            step = base / "step.sh"
            step.write_text(source.replace("/etc/agentainer", str(image))
                                  .replace("/usr/local/lib/agentainer/release_version.py", str(HELPER)))
            shell = HOME_PATH + '''seed_file() { [ -e "$2" ] || [ -L "$2" ] || { mkdir -p "$(dirname "$2")" && cp "$1" "$2"; }; }
log() { printf '%s\n' "$*"; }
warn() { printf '%s\n' "$*"; }
. "$1"
'''
            result = subprocess.run(["sh", "-ec", shell, "sh", str(step)],
                                    env=dict(os.environ, HOME=str(home), AGENTAINER_IMAGE_VERSION=candidate),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(canon.stat().st_mode & 0o777, 0o600)
            lines = ledger.read_text().splitlines()
            self.assertIn(hashlib.sha256(b"new default\n").hexdigest() + " " + candidate, lines)
            user = hashlib.sha256((old + "user edit\n").encode()).hexdigest()
            self.assertFalse([line for line in lines if line.split()[0] == user], lines)
            return canon.read_text()

    def test_newer_prerelease_updates_older_prerelease_default(self):
        self.assertEqual(self.apply("0.1.0-dev.20261019.10", ["0.1.0-dev.20261019.2"]), "new default\n")

    def test_older_prerelease_does_not_roll_back_default(self):
        self.assertEqual(self.apply("0.1.0-dev.20261019.2", ["0.1.0-dev.20261019.10"]), "old default\n")

    def test_future_prerelease_keeps_stable_default(self):
        self.assertEqual(self.apply("0.2.0-dev.20261019.1", ["0.1.0"]), "old default\n")

    def test_stable_replaces_prerelease_default(self):
        self.assertEqual(self.apply("0.1.0", ["0.1.0-dev.20261019.1"]), "new default\n")

    def test_local_dev_keeps_default(self):
        self.assertEqual(self.apply("dev", ["0.1.0"]), "old default\n")

    def test_user_edit_is_preserved(self):
        self.assertEqual(self.apply("0.2.0", ["0.1.0"], edited=True), "old default\nuser edit\n")
