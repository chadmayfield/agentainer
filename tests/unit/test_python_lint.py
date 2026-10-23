import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "lint_python", Path(__file__).resolve().parents[2] / "scripts/lint-python.py")
lint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lint)


class PythonDiscoveryTests(unittest.TestCase):
    def test_includes_build_and_extensionless_python_but_skips_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, text in {
                "build/check.py": "print('check')\n",
                "rootfs/usr/local/bin/helper": "#!/usr/bin/python3 -I\nprint('helper')\n",
                "bin/shell": "#!/bin/sh\necho shell\n",
                "tests/node_modules/vendor.py": "not Python\n",
                "scripts/__pycache__/cached.py": "not Python\n",
            }.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            self.assertEqual(lint.python_files(root), [
                "build/check.py", "rootfs/usr/local/bin/helper"])
