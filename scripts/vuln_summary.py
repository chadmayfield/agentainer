#!/usr/bin/env python3
"""Print a short Markdown summary of trivy JSON reports, one column per architecture.

Usage: scripts/vuln_summary.py ARCH=REPORT.json [ARCH=REPORT.json ...]

CI writes the result to the job summary (limited to 1 MiB) and to release notes,
so it lists counts by severity and at most 50 critical findings. The full JSON
reports are uploaded next to it.
"""
import collections
import json
import sys

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")
MAX_CRITICAL = 50


def load(path):
    with open(path) as f:
        data = json.load(f)
    return [v for r in data.get("Results") or [] for v in r.get("Vulnerabilities") or []]


def summary(reports):
    arches = [a for a, _ in reports]
    counts = {}
    critical = collections.OrderedDict()
    for arch, path in reports:
        vulns = load(path)
        counts[arch] = collections.Counter(v.get("Severity", "UNKNOWN") for v in vulns)
        for v in vulns:
            if v.get("Severity") != "CRITICAL":
                continue
            key = (v.get("VulnerabilityID", ""), v.get("PkgName", ""),
                   v.get("InstalledVersion", ""), v.get("FixedVersion", ""))
            critical.setdefault(key, [])
            if arch not in critical[key]:
                critical[key].append(arch)
    lines = ["### Vulnerabilities (trivy, report only)", "",
             "| Severity | " + " | ".join(arches) + " |",
             "|---|" + "---|" * len(arches)]
    for s in SEVERITIES:
        lines.append("| %s | %s |" % (s, " | ".join(str(counts[a].get(s, 0)) for a in arches)))
    if critical:
        lines += ["", "| Critical | Package | Installed | Fixed in | Architectures |", "|---|---|---|---|---|"]
        for key, where in sorted(critical.items())[:MAX_CRITICAL]:
            lines.append("| %s | %s | %s | %s | %s |" % (key + (", ".join(where),)))
        if len(critical) > MAX_CRITICAL:
            lines.append("")
            lines.append("%d more critical findings are in the full reports." % (len(critical) - MAX_CRITICAL))
    return "\n".join(lines) + "\n"


def main(argv):
    pairs = []
    for arg in argv:
        arch, sep, path = arg.partition("=")
        if not sep or not arch or not path:
            print("usage: vuln_summary.py ARCH=REPORT.json [...]", file=sys.stderr)
            return 2
        pairs.append((arch, path))
    if not pairs:
        print("usage: vuln_summary.py ARCH=REPORT.json [...]", file=sys.stderr)
        return 2
    sys.stdout.write(summary(pairs))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
