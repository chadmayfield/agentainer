"""Exercise native tools offline. PostgreSQL server execution is a separate check."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


class BuildTools(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="cx-build-tools-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def run_tool(self, *args, expected=0, env=None):
        completed = subprocess.run(args, cwd=self.root, env=env, text=True,
                                   capture_output=True, timeout=60)
        self.assertEqual(completed.returncode, expected, completed.stdout + completed.stderr)
        return completed.stdout.strip()

    def test_cmake_ninja_builds_and_rejects_broken_source(self):
        (self.root / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.16)\n"
            "project(agentainer_fixture LANGUAGES C CXX)\n"
            "add_executable(example example.cpp)\n")
        source = self.root / "example.cpp"
        source.write_text('#include <iostream>\nint main() { std::cout << "NATIVE_OK"; }\n')
        self.run_tool("cmake", "-S", ".", "-B", "build", "-G", "Ninja")
        self.run_tool("cmake", "--build", "build")
        self.assertEqual(self.run_tool(str(self.root / "build/example")), "NATIVE_OK")
        source.write_text("this is deliberately invalid C++;\n")
        self.run_tool("cmake", "--build", "build", expected=1)

    def test_ninja_executes(self):
        self.assertTrue(self.run_tool("ninja", "--version"))

    def test_pkg_config_flags_compile_a_program(self):
        (self.root / "fixture.h").write_text("#define FIXTURE_RESULT 42\n")
        (self.root / "fixture.pc").write_text(
            "Name: agentainer-fixture\nDescription: Local compiler metadata fixture\n"
            "Version: 1.0.0\nCflags: -I" + str(self.root) + " -DFIXTURE_ENABLED=1\n")
        environment = dict(os.environ, PKG_CONFIG_LIBDIR=str(self.root), PKG_CONFIG_PATH="")
        self.assertEqual(self.run_tool("pkg-config", "--modversion", "fixture", env=environment), "1.0.0")
        flags = shlex.split(self.run_tool("pkg-config", "--cflags", "fixture", env=environment))
        source = self.root / "example.c"
        source.write_text('#include "fixture.h"\nint main(void) {\n'
                          "return FIXTURE_ENABLED && FIXTURE_RESULT == 42 ? 0 : 1;\n}\n")
        self.run_tool("cc", *flags, str(source), "-o", "example")
        self.run_tool(str(self.root / "example"))
        self.run_tool("pkg-config", "--exists", "cx-missing-package", expected=1, env=environment)

    def test_psql_executes_and_reports_connection_failure(self):
        self.assertIn("PostgreSQL", self.run_tool("psql", "--version"))
        script = self.root / "example.sql"
        script.write_text("SELECT 42;\n")
        # A private directory cannot contain a server socket. Ignore all inherited
        # libpq options so this check cannot connect to a user's database.
        environment = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
        self.run_tool("psql", "--no-psqlrc", "--no-password", "--host", str(self.root),
                      "--port", "5432", "--username", "fixture", "--dbname", "fixture",
                      "--set", "ON_ERROR_STOP=1", "--file", str(script),
                      expected=2, env=environment)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BuildTools)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("BUILD_TOOLS_VERIFIED")
