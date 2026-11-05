import importlib.util
import os
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

    def test_missing_file_is_unknown(self):
        self.assertEqual(wvj.read_apt_source("/nonexistent/apt-source"), "unknown")


if __name__ == "__main__":
    unittest.main()
