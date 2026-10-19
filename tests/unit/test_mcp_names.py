import importlib.machinery
import importlib.util
import json
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(__file__)
SRC = os.path.join(HERE, "..", "..", "rootfs", "usr", "local", "bin", "agentainer-mcp")
loader = importlib.machinery.SourceFileLoader("agentainer_mcp_names", SRC)
spec = importlib.util.spec_from_loader("agentainer_mcp_names", loader)
mcp = importlib.util.module_from_spec(spec)
loader.exec_module(mcp)


class ServerNames(unittest.TestCase):
    """Server names in mcp.json may use only letters, digits, - and _."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.path = os.path.join(self.tmp, "mcp.json")

    def load(self, name):
        with open(self.path, "w") as f:
            json.dump({"mcpServers": {name: {"command": "true"}}}, f)
        return mcp.load_desired(self.path)

    def test_accepts_letters_digits_dash_underscore(self):
        self.assertIn("my-Server_2", self.load("my-Server_2"))

    def test_rejects_a_dot(self):
        with self.assertRaises(mcp.Invalid):
            self.load("my.server")

    def test_rejects_a_trailing_newline(self):
        # "$" in a regex also matches before a final newline, so the whole name must match.
        with self.assertRaises(mcp.Invalid):
            self.load("server\n")


if __name__ == "__main__":
    unittest.main()
