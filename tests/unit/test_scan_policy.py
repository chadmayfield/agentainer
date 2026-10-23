"""Keep release secret checks independent of the candidate image."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


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
        import fnmatch
        for file in (".containerignore", "Containerfile.dockerignore"):
            patterns = (ROOT / file).read_text().splitlines()
            for path in ("env", "host.key", "rootfs/env", "rootfs/host.key", ".env"):
                self.assertTrue(any(fnmatch.fnmatch(path, pattern) for pattern in patterns), (file, path))

    def test_ca_bootstrap_bundle_does_not_enter_a_final_copy_layer(self):
        text = (ROOT / "Containerfile").read_text()
        self.assertNotIn("COPY --from=certs", text)
        self.assertIn("--mount=type=bind,from=certs", text)
