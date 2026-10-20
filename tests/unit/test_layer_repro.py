import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("repro", ROOT / "tests/host/test-layer-repro.py")
repro = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repro)


class LayerExportTests(unittest.TestCase):
    def archive(self, path, index, objects):
        with tarfile.open(path, "w") as archive:
            for name, value in {"index.json": index, **objects}.items():
                data = json.dumps(value).encode()
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))

    def test_reads_nested_oci_indexes_without_accepting_attestations_as_images(self):
        first, second = "1" * 64, "2" * 64
        index = {"manifests": [{"digest": "sha256:" + first}]}
        nested = {"manifests": [{"digest": "sha256:" + second, "platform": {"os": "linux"}},
                                {"digest": "sha256:" + "3" * 64, "platform": {"os": "unknown"}}]}
        expected = ["sha256:" + "a" * 64, "sha256:" + "b" * 64]
        with tempfile.TemporaryDirectory(prefix="cx-oci-") as d:
            path = Path(d) / "export.tar"
            self.archive(path, index, {"blobs/sha256/" + first: nested,
                                      "blobs/sha256/" + second: {"layers": [{"digest": x} for x in expected]}})
            self.assertEqual(repro.layers(path), expected)

    def test_rejects_empty_ambiguous_and_invalid_descriptor_indexes(self):
        cases = [[], [{"digest": "sha256:bad"}],
                 [{"digest": "sha256:" + "1" * 64}, {"digest": "sha256:" + "2" * 64}]]
        with tempfile.TemporaryDirectory(prefix="cx-oci-") as d:
            path = Path(d) / "export.tar"
            for manifests in cases:
                with self.subTest(manifests=manifests):
                    self.archive(path, {"manifests": manifests}, {})
                    with self.assertRaises(ValueError):
                        repro.layers(path)
