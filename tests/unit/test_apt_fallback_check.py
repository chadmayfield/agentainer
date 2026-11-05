"""scripts/check-apt-fallback.sh: warn when the image build fell back, fail when the change touches the snapshot inputs."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check-apt-fallback.sh"
SNAP = "20261104T000000Z"
FALLBACK = "archive-fallback 2026-11-05 (snapshot %s unavailable)" % SNAP


class AptFallbackCheckTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(prefix="cx-apt-fallback-")
        self.addCleanup(self.dir.cleanup)
        self.repo = Path(self.dir.name) / "repo"
        self.repo.mkdir()
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null",
                        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
        self.git("init", "-q", "-b", "develop")
        (self.repo / "build").mkdir()
        self.write("versions.env", "APT_SNAPSHOT=%s\nGO_VERSION=1.27.3\n" % SNAP)
        self.write("build/apt-packages.txt", "git\n")
        self.write("README.md", "a\n")
        self.commit("base")
        self.base = self.git("rev-parse", "HEAD")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, env=self.env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def write(self, name, text):
        (self.repo / name).write_text(text)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def pull_request(self, files):
        """Leaves HEAD at a test merge commit of the base and a branch that changes files."""
        self.git("checkout", "-q", "-b", "pr")
        for name, text in files.items():
            self.write(name, text)
        self.commit("change")
        head = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "develop")
        self.git("merge", "-q", "--no-ff", "-m", "merge", "pr")
        return head

    def run_check(self, apt_source, rc=0, **extra):
        engine = Path(self.dir.name) / "engine"
        engine.write_text("#!/bin/sh\nprintf '%s\\n' \"$CX_APT_SOURCE\"\nexit \"${CX_APT_RC:-0}\"\n")
        engine.chmod(0o755)
        env = dict(self.env, RUNTIME=str(engine), CX_APT_SOURCE=apt_source, CX_APT_RC=str(rc))
        env.update(extra)
        return subprocess.run(["sh", str(SCRIPT), "localhost/agentainer:dev"], cwd=self.repo, env=env,
                              capture_output=True, text=True)

    def test_snapshot_build_is_silent_and_passes(self):
        head = self.pull_request({"versions.env": "APT_SNAPSHOT=20261105T000000Z\nGO_VERSION=1.27.3\n"})
        result = self.run_check("snapshot " + SNAP, EVENT="pull_request", PR_HEAD=head)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("::warning", result.stdout)

    def test_fallback_on_an_unrelated_change_warns_and_passes(self):
        head = self.pull_request({"README.md": "b\n", "versions.env": "APT_SNAPSHOT=%s\nGO_VERSION=1.28.0\n" % SNAP})
        result = self.run_check(FALLBACK, EVENT="pull_request", PR_HEAD=head)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("::warning title=apt snapshot fallback::", result.stdout)
        self.assertIn(SNAP, result.stdout)

    def test_fallback_fails_when_the_change_modifies_the_snapshot(self):
        head = self.pull_request({"versions.env": "APT_SNAPSHOT=20261105T000000Z\nGO_VERSION=1.27.3\n"})
        result = self.run_check(FALLBACK, EVENT="pull_request", PR_HEAD=head)
        self.assertEqual(result.returncode, 1)
        self.assertIn("::error", result.stdout)
        self.assertIn("::warning", result.stdout)

    def test_fallback_fails_when_the_change_modifies_the_package_list(self):
        head = self.pull_request({"build/apt-packages.txt": "git\nnewpkg\n"})
        result = self.run_check(FALLBACK, EVENT="pull_request", PR_HEAD=head)
        self.assertEqual(result.returncode, 1)
        self.assertIn("::error", result.stdout)

    def test_fallback_on_a_push_compares_with_the_previous_tip(self):
        self.write("build/apt-packages.txt", "git\nnewpkg\n")
        self.commit("add package")
        result = self.run_check(FALLBACK, EVENT="push", REF="refs/heads/develop", BEFORE=self.base)
        self.assertEqual(result.returncode, 1)
        self.write("README.md", "c\n")
        self.commit("docs")
        before = self.git("rev-parse", "HEAD~1")
        result = self.run_check(FALLBACK, EVENT="push", REF="refs/heads/develop", BEFORE=before)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("::warning", result.stdout)

    def test_fallback_without_a_base_warns_and_passes(self):
        result = self.run_check(FALLBACK, EVENT="workflow_dispatch")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("::warning", result.stdout)

    def test_failed_git_diff_fails_the_check(self):
        real = subprocess.run(["which", "git"], capture_output=True, text=True, check=True).stdout.strip()
        shim = Path(self.dir.name) / "shim"
        shim.mkdir()
        (shim / "git").write_text('#!/bin/sh\n[ "$1" = diff ] && { echo "fatal: bad diff" >&2; exit 128; }\nexec %s "$@"\n' % real)
        (shim / "git").chmod(0o755)
        self.write("README.md", "d\n")
        self.commit("docs")
        result = self.run_check(FALLBACK, EVENT="push", REF="refs/heads/develop", BEFORE=self.base,
                                PATH=str(shim) + ":" + os.environ["PATH"])
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("not checked", result.stdout)

    def test_unreadable_apt_source_fails(self):
        result = self.run_check("", rc=1, EVENT="workflow_dispatch")
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
