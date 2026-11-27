"""Run the Kubernetes example's transfer-links init container command on a scratch folder."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
STATEFULSET = ROOT / "deploy/kubernetes/agentainer/statefulset.yaml"


def command():
    """The init container's sh -ec script, from its one-line command entry."""
    text = STATEFULSET.read_text()
    block = text.split("- name: transfer-links", 1)[1]
    return re.search(r"^\s*command: \[sh, -ec, '(.*)'\]$", block, re.M).group(1)


@unittest.skipUnless(shutil.which("find"), "needs find")
class TransferLinksTests(unittest.TestCase):
    def test_links_are_removed_and_their_targets_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            transfer = base / "transfer"
            outside = base / "outside"
            (transfer / "reports").mkdir(parents=True)
            outside.mkdir()
            (outside / "keep.txt").write_text("target\n")
            (transfer / "reports/q3.pdf").write_text("pdf\n")
            (transfer / "planted-dir").symlink_to(outside)
            (transfer / "reports/planted-file").symlink_to(outside / "keep.txt")
            (transfer / "dangling").symlink_to(base / "missing")
            script = command().replace("/srv/transfer", str(transfer))
            result = subprocess.run(["sh", "-ec", script], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            remaining = sorted(str(p.relative_to(transfer)) for p in transfer.rglob("*"))
            self.assertEqual(remaining, ["reports", "reports/q3.pdf"])
            self.assertEqual((outside / "keep.txt").read_text(), "target\n")
            for name in ("planted-dir", "reports/planted-file", "dangling"):
                self.assertIn(str(transfer / name), result.stdout)

    def test_an_empty_folder_succeeds(self):
        with tempfile.TemporaryDirectory() as directory:
            script = command().replace("/srv/transfer", directory)
            result = subprocess.run(["sh", "-ec", script], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(Path(directory).is_dir())


if __name__ == "__main__":
    unittest.main()
