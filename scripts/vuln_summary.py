#!/usr/bin/env python3
"""Print a short Markdown summary of trivy JSON reports, one column per architecture.

Usage: scripts/vuln_summary.py ARCH=REPORT.json [ARCH=REPORT.json ...]

CI writes the result to the job summary (limited to 1 MiB) and to release notes,
so it lists counts by severity, at most 50 critical findings, and fixable findings
in upstream Go executables. The full JSON reports are uploaded next to it.
"""
import collections
import json
import sys

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")
MAX_CRITICAL = 50
# Kernel CVEs filed against the kernel header package. It holds only .h files that
# glibc and every C compile need; a container runs on the host's kernel.
KERNEL_HEADERS = "linux-libc-dev"


def load(path):
    with open(path) as f:
        data = json.load(f)
    return data.get("Results") or []


def summary(reports):
    arches = [a for a, _ in reports]
    counts, fixable, headers = {}, {}, {}
    critical = collections.OrderedDict()
    upstream = {}
    for arch, path in reports:
        results = load(path)
        everything = [v for r in results for v in r.get("Vulnerabilities") or []]
        vulns = [v for v in everything if v.get("PkgName") != KERNEL_HEADERS]
        headers[arch] = len(everything) - len(vulns)
        counts[arch] = collections.Counter(v.get("Severity", "UNKNOWN") for v in vulns)
        fixable[arch] = collections.Counter(v.get("Severity", "UNKNOWN") for v in vulns if v.get("FixedVersion"))
        for result in results:
            if result.get("Type") != "gobinary":
                continue
            n = sum(bool(v.get("FixedVersion")) for v in result.get("Vulnerabilities") or [])
            if n:
                where = upstream.setdefault(result["Target"], {})
                where[arch] = where.get(arch, 0) + n
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
    def cell(a, s):
        n, f = counts[a].get(s, 0), fixable[a].get(s, 0)
        return "%d (%d fixable)" % (n, f) if f else str(n)
    for s in SEVERITIES:
        lines.append("| %s | %s |" % (s, " | ".join(cell(a, s) for a in arches)))
    lines += ["", "Fixable means a fixed version exists upstream or in Ubuntu."]
    if any(headers.values()):
        lines += ["", "Not counted above: kernel CVEs filed against `%s`, the kernel header files "
                  "that C compilers need. The container runs on the host's kernel. %s." % (
                      KERNEL_HEADERS, ", ".join("%s %d" % (a, headers[a]) for a in arches))]
    if critical:
        lines += ["", "| Critical | Package | Installed | Fixed in | Architectures |", "|---|---|---|---|---|"]
        for key, where in sorted(critical.items())[:MAX_CRITICAL]:
            lines.append("| %s | %s | %s | %s | %s |" % (key + (", ".join(where),)))
        if len(critical) > MAX_CRITICAL:
            lines.append("")
            lines.append("%d more critical findings are in the full reports." % (len(critical) - MAX_CRITICAL))
    if upstream:
        lines += ["", "### Fixable findings in upstream executables", "",
                  "These findings are in Go code embedded in the executables below. "
                  "Fixed versions refer to Go or its dependencies and do not necessarily identify a published tool binary. "
                  "Agentainer installs upstream release binaries rather than rebuilding bundled tools. "
                  "Where a patched executable is not yet available, we are waiting for its upstream release.", "",
                  "Counts include the same vulnerability reported against different executables.", "",
                  "| Upstream executable | " + " | ".join(arches) + " |",
                  "|---|" + "---|" * len(arches)]
        for target, where in sorted(upstream.items()):
            lines.append("| `%s` | %s |" % (target, " | ".join(str(where.get(a, 0)) for a in arches)))
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
