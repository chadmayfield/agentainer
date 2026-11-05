import importlib.util
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(__file__)
spec = importlib.util.spec_from_file_location(
    "write_versions_json", os.path.join(HERE, "..", "..", "build", "write-versions-json.py"))
wvj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wvj)


class AptSourceTests(unittest.TestCase):
    def write(self, text):
        f = tempfile.NamedTemporaryFile("w", delete=False)
        f.write(text)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_reads_the_one_line(self):
        self.assertEqual(wvj.read_apt_source(self.write("snapshot 20261104T000000Z\n")), "snapshot 20261104T000000Z")

    def test_main_writes_apt_source_into_versions_json(self):
        import json
        from unittest.mock import patch
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        env = self.write("GO_VERSION=1.27.3\n# comment\n")
        line = "archive-fallback 2026-11-05 (snapshot 20261104T000000Z unavailable)"
        with patch.object(wvj.subprocess, "check_output", return_value="git 1:2.53.0-1\nzip 3.0\n"):
            wvj.main(env, directory, self.write(line + "\n"))
        with open(os.path.join(directory, "versions.json")) as f:
            data = json.load(f)
        self.assertEqual(data["apt_source"], line)
        self.assertEqual(data["pins"], {"GO_VERSION": "1.27.3"})
        self.assertEqual(data["apt"], {"git": "1:2.53.0-1", "zip": "3.0"})

    def test_missing_file_is_unknown(self):
        self.assertEqual(wvj.read_apt_source("/nonexistent/apt-source"), "unknown")


if __name__ == "__main__":
    unittest.main()
