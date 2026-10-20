import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("published", ROOT / "tests/host/test-published-image.py")
published = importlib.util.module_from_spec(spec)
spec.loader.exec_module(published)


class PublishedImageTests(unittest.TestCase):
    def setUp(self):
        self.image = "registry.example.com/agentainer"
        self.identity = "https://github.com/example/repo/.github/workflows/build.yml@refs/heads/main"
        self.issuer = "https://token.actions.githubusercontent.com"
        self.root = "sha256:" + "0" * 64
        self.children = ["sha256:" + x * 64 for x in ("1", "2")]
        self.attestations = ["sha256:" + x * 64 for x in ("3", "4")]
        self.index = {"manifests": []}
        self.documents = {}
        for arch, child, att in zip(("amd64", "arm64"), self.children, self.attestations):
            self.index["manifests"] += [
                {"digest": child, "platform": {"os": "linux", "architecture": arch}},
                {"digest": att, "annotations": {"vnd.docker.reference.type": "attestation-manifest",
                                               "vnd.docker.reference.digest": child}}]
            self.documents[self.image + "@" + att] = {"layers": [
                {"mediaType": "application/vnd.in-toto+json", "annotations": {"in-toto.io/predicate-type": predicate}}
                for predicate in ("https://spdx.dev/Document", "https://slsa.dev/provenance/v1")]}
        self.calls = []
        self.bad_signature = None

    def stub_run(self, argv):
        self.calls.append(argv)
        if argv[0] == "cosign":
            if argv[2] == self.bad_signature:
                raise subprocess.CalledProcessError(1, argv)
            return "[]"
        if "--format" in argv:
            return json.dumps({"digest": self.root})
        ref = argv[-1]
        return json.dumps(self.index if ref == self.image + "@" + self.root else self.documents[ref])

    def verify(self):
        with mock.patch.object(published, "run", side_effect=self.stub_run):
            return published.verify(self.image, "sha-test", self.identity, self.issuer)

    def test_checks_index_and_both_platforms_with_exact_workflow_identity(self):
        self.assertEqual(self.verify(), self.image + "@" + self.root)
        signed = [c for c in self.calls if c[0] == "cosign"]
        self.assertEqual([c[2] for c in signed], [self.image + "@" + d for d in [self.root] + self.children])
        for command in signed:
            self.assertEqual(command[command.index("--certificate-identity") + 1], self.identity)
            self.assertEqual(command[command.index("--certificate-oidc-issuer") + 1], self.issuer)

    def test_rejects_missing_or_duplicate_architectures(self):
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate):
                saved = copy.deepcopy(self.index)
                if duplicate:
                    self.index["manifests"].append(copy.deepcopy(self.index["manifests"][0]))
                else:
                    self.index["manifests"] = self.index["manifests"][1:]
                with self.assertRaises(ValueError):
                    self.verify()
                self.index = saved

    def test_each_platform_requires_sbom_and_provenance(self):
        for att in self.attestations:
            for removed in (0, 1):
                with self.subTest(att=att, removed=removed):
                    key = self.image + "@" + att
                    saved = copy.deepcopy(self.documents[key])
                    self.documents[key]["layers"].pop(removed)
                    with self.assertRaises(ValueError):
                        self.verify()
                    self.documents[key] = saved

    def test_attestation_must_be_bound_to_the_correct_platform_digest(self):
        self.index["manifests"][1]["annotations"]["vnd.docker.reference.digest"] = self.children[1]
        with self.assertRaises(ValueError):
            self.verify()

    def test_a_bad_platform_signature_fails(self):
        self.bad_signature = self.image + "@" + self.children[1]
        with self.assertRaises(subprocess.CalledProcessError):
            self.verify()

    def test_rejects_a_malformed_digest_before_verification(self):
        self.root = "sha256:bad"
        with self.assertRaises(ValueError):
            self.verify()
        self.assertFalse(any(c[0] == "cosign" for c in self.calls))

    def test_digest_input_does_not_resolve_a_mutable_tag(self):
        with mock.patch.object(published, "run", side_effect=self.stub_run):
            self.assertEqual(published.verify(self.image, self.root, self.identity, self.issuer),
                             self.image + "@" + self.root)
        self.assertFalse(any("--format" in c for c in self.calls))

    def test_malformed_digest_input_fails_before_registry_calls(self):
        with mock.patch.object(published, "run", side_effect=self.stub_run):
            with self.assertRaises(ValueError):
                published.verify(self.image, "sha256:bad", self.identity, self.issuer)
        self.assertEqual(self.calls, [])
