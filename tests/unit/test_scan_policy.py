"""Keep release secret checks independent of the candidate image."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ignorefile  # noqa: E402

SECRET_PATHS = ("env", "host.key", ".env", ".env.local", "rootfs/env", "rootfs/host.key",
                "rootfs/.env", "rootfs/etc/.env.local")


class ScanPolicyTests(unittest.TestCase):
    def test_candidate_and_published_images_use_independent_secret_scans(self):
        text = (ROOT / ".github/workflows/build.yml").read_text()
        self.assertNotIn("--entrypoint trivy", text)
        self.assertNotIn("trivy-secret.yaml", text)
        for block in (text.split("  image:\n", 1)[1].split("  layer-repro:\n", 1)[0],
                      text.split("  publish:\n", 1)[1].split("  release:\n", 1)[0]):
            self.assertIn("TRIVY_SCANNER_IMAGE", block)
            self.assertIn("--scanners secret --exit-code 1", block)

    def test_both_build_contexts_exclude_known_secret_paths(self):
        for file in (".containerignore", "Containerfile.dockerignore"):
            text = (ROOT / file).read_text()
            for path in SECRET_PATHS:
                with self.subTest(file=file, path=path):
                    self.assertTrue(ignorefile.docker_excludes(text, path), "Docker keeps it")
                    self.assertTrue(ignorefile.podman_excludes(text, path), "Podman keeps it")

    def test_ignore_matcher_rejects_patterns_that_miss_nested_secrets(self):
        good = (ROOT / ".containerignore").read_text()
        cases = (
            ("*.key\n*env\n", "rootfs/host.key"),
            ("*.key\n*env\n", "rootfs/env"),
            (good + "!rootfs/host.key\n", "rootfs/host.key"),
            ("# env\n", "env"),
            ("rootfs/*.key\n", "rootfs/etc/host.key"),
        )
        for text, path in cases:
            with self.subTest(text=text, path=path):
                self.assertFalse(ignorefile.docker_excludes(text, path))
                self.assertFalse(ignorefile.podman_excludes(text, path))
        for text, path in (("rootfs\n", "rootfs/etc/x"), ("**/*.key\n", "rootfs/a/host.key"),
                           ("env\n!env\nenv\n", "env")):
            with self.subTest(text=text, path=path):
                self.assertTrue(ignorefile.excluded_by_both(text, path))

    def test_ca_bootstrap_bundle_does_not_enter_a_final_copy_layer(self):
        text = (ROOT / "Containerfile").read_text()
        self.assertNotIn("COPY --from=certs", text)
        self.assertIn("--mount=type=bind,from=certs", text)
