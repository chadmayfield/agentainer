import importlib.util
import json
import os
import tempfile
import unittest

HERE = os.path.dirname(__file__)
spec = importlib.util.spec_from_file_location(
    "vuln_summary", os.path.join(HERE, "..", "..", "scripts", "vuln_summary.py"))
vs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vs)


def report(vulns):
    return {"Results": [{"Target": "usr/local/bin/x", "Vulnerabilities": vulns}, {"Target": "clean"}]}


def v(vid, sev, pkg="pkg", installed="1", fixed="2"):
    return {"VulnerabilityID": vid, "Severity": sev, "PkgName": pkg,
            "InstalledVersion": installed, "FixedVersion": fixed}


class VulnSummaryTests(unittest.TestCase):
    def write(self, data):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(data, f)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_counts_each_architecture(self):
        a = self.write(report([v("CVE-1", "HIGH"), v("CVE-2", "LOW"), v("CVE-3", "HIGH")]))
        b = self.write(report([v("CVE-4", "MEDIUM")]))
        out = vs.summary([("amd64", a), ("arm64", b)])
        self.assertIn("| Severity | amd64 | arm64 |", out)
        self.assertIn("| HIGH | 2 | 0 |", out)
        self.assertIn("| MEDIUM | 0 | 1 |", out)
        self.assertIn("| CRITICAL | 0 | 0 |", out)

    def test_lists_critical_once_with_its_architectures(self):
        crit = v("CVE-9", "CRITICAL", "stdlib", "v1.24.1", "1.24.13")
        a = self.write(report([crit]))
        b = self.write(report([crit]))
        out = vs.summary([("amd64", a), ("arm64", b)])
        self.assertEqual(out.count("CVE-9"), 1)
        self.assertIn("| CVE-9 | stdlib | v1.24.1 | 1.24.13 | amd64, arm64 |", out)

    def test_report_without_results(self):
        out = vs.summary([("amd64", self.write({"SchemaVersion": 2}))])
        self.assertIn("| HIGH | 0 |", out)
        self.assertNotIn("| Critical |", out)

    def test_stays_small(self):
        many = [v("CVE-%d" % i, "CRITICAL") for i in range(500)]
        out = vs.summary([("amd64", self.write(report(many)))])
        self.assertLess(len(out.encode()), 20000)
        self.assertIn("450 more", out)


if __name__ == "__main__":
    unittest.main()
