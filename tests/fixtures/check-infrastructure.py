"""Verify pinned clients and local rendering without cluster access."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

pins = json.loads(Path("/etc/agentainer/versions.json").read_text())["pins"]


def require(condition, message="fixture condition failed"):
    if not condition:
        raise SystemExit(message)


def command(arguments, expected=0):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=20)
    if expected == 0:
        require(result.returncode == 0, result.stderr)
    else:
        require(result.returncode != 0, "broken input was accepted")
    return result.stdout


version = json.loads(command(["kubectl", "version", "--client=true", "--output=json"]))
require(version["clientVersion"]["gitVersion"] == "v" + pins["KUBECTL_VERSION"], version)
require(command(["helm", "version", "--short"]).strip().split("+")[0] == "v" + pins["HELM_VERSION"], 'fixture condition failed')

with tempfile.TemporaryDirectory(prefix="cx-infrastructure-") as directory:
    base = Path(directory)
    os.environ["KUBECONFIG"] = str(base / "no-cluster-config")
    kustomize = base / "kustomize"
    kustomize.mkdir()
    (kustomize / "kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
        "namespace: cx-offline\nresources:\n  - configmap.yaml\n")
    (kustomize / "configmap.yaml").write_text(
        "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: fixture\ndata:\n  message: hello\n")
    rendered = command(["kubectl", "kustomize", str(kustomize)])
    for expected in ("kind: ConfigMap", "namespace: cx-offline", "name: fixture", "message: hello"):
        require(expected in rendered, rendered)
    (kustomize / "configmap.yaml").unlink()
    command(["kubectl", "kustomize", str(kustomize)], expected=1)

    chart = base / "chart"
    templates = chart / "templates"
    templates.mkdir(parents=True)
    (chart / "Chart.yaml").write_text("apiVersion: v2\nname: cx-fixture\nversion: 0.1.0\n")
    (chart / "values.yaml").write_text("message: hello\n")
    template = templates / "configmap.yaml"
    template.write_text('apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: {{ .Release.Name }}\n'
                        'data:\n  message: {{ .Values.message | quote }}\n')
    rendered = command(["helm", "template", "cx-offline", str(chart)])
    for expected in ("kind: ConfigMap", "name: cx-offline", 'message: "hello"'):
        require(expected in rendered, rendered)
    template.write_text("{{ missing_function }}\n")
    command(["helm", "template", "cx-offline", str(chart)], expected=1)

print("INFRASTRUCTURE_VERIFIED")
