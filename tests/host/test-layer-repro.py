#!/usr/bin/env python3
"""Build isolated copies of every tool twice and compare their exported layer digests.

Requires a configured Buildx builder. Exporter flags:
https://docs.docker.com/build/exporters/oci-docker/
https://docs.docker.com/build/exporters/reproducibility/
"""
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def layers(path):
    with tarfile.open(path) as archive:
        def read(name):
            f = archive.extractfile(name)
            if f is None:
                raise ValueError("missing OCI object: " + name)
            return json.load(f)
        doc = read("index.json")
        while "manifests" in doc:
            choices = [m for m in doc["manifests"] if m.get("platform", {}).get("os") != "unknown"]
            if len(choices) != 1:
                raise ValueError("expected one image in OCI export")
            algorithm, value = choices[0]["digest"].split(":", 1)
            if algorithm != "sha256" or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError("invalid OCI descriptor digest")
            doc = read("blobs/sha256/" + value)
        return [layer["digest"] for layer in doc["layers"]]


def main():
    source = (ROOT / "Containerfile").read_text()
    copies = [line for line in source.splitlines() if line.startswith("COPY --from=")
              and not line.startswith("COPY --from=certs ")]
    if not copies:
        raise SystemExit("no tool copies found")
    declared = set(re.findall(r"^ARG ([A-Z0-9_]+)", source, re.M)) | {"SOURCE_DATE_EPOCH"}
    pins = dict(line.split("=", 1) for line in (ROOT / "versions.env").read_text().splitlines()
                if line and not line.startswith("#"))
    with tempfile.TemporaryDirectory(prefix="cx-layer-repro-") as d:
        tmp = Path(d)
        probe = tmp / "Containerfile"
        probe.write_text(source + "\nFROM scratch AS cx_layer_probe\n" + "\n".join(copies) + "\n")
        exports = []
        for attempt in (1, 2):
            output = tmp / ("probe-%d.tar" % attempt)
            command = ["docker", "buildx", "build", "--no-cache", "--provenance=false",
                       "--target", "cx_layer_probe", "-f", str(probe), "--output",
                       "type=oci,dest=%s,rewrite-timestamp=true" % output]
            for name, value in pins.items():
                if name in declared:
                    command += ["--build-arg", name + "=" + value]
            subprocess.run(command + [str(ROOT)], check=True)
            exports.append(layers(output))
        if len(exports[0]) != len(copies) or exports[0] != exports[1]:
            print(json.dumps({"copies": copies, "first": exports[0], "second": exports[1]}, indent=2))
            raise SystemExit("unchanged tool layers differ between clean builds")
        print("Verified %d tool COPY layers across two clean builds" % len(copies))


if __name__ == "__main__":
    main()
