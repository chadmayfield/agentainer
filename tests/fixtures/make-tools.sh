#!/bin/bash
# Builds small offline install fixtures in a new directory and prints its path:
#   fixture.tgz     an npm package (bin: fixture-npm)
#   gomod/          a Go module (installs a binary named fixture)
#   fixture_uv-1.0-py3-none-any.whl   a wheel (console script: fixture-uv)
# Runs inside the image, so the tools tests need no package registry.
set -euo pipefail
d=$(mktemp -d)
cd "$d"

mkdir npmpkg
printf '{"name":"agentainer-fixture","version":"1.0.0","bin":{"fixture-npm":"cli.js"}}\n' >npmpkg/package.json
printf '#!/usr/bin/env node\nconsole.log("fixture-npm ok")\n' >npmpkg/cli.js
(cd npmpkg && npm pack --silent >/dev/null)
mv npmpkg/agentainer-fixture-1.0.0.tgz fixture.tgz

mkdir gomod
(cd gomod && go mod init example.com/fixture >/dev/null 2>&1)
printf 'package main\n\nimport "fmt"\n\nfunc main() { fmt.Println("fixture-go ok") }\n' >gomod/main.go

# A wheel is a zip with a RECORD of sha256 hashes; building it by hand avoids a build backend.
python3 - <<'EOF'
import base64
import hashlib
import zipfile

files = {
    "fixture_uv/__init__.py": "def main():\n    print(\"fixture-uv ok\")\n",
    "fixture_uv-1.0.dist-info/METADATA": "Metadata-Version: 2.1\nName: fixture-uv\nVersion: 1.0\n",
    "fixture_uv-1.0.dist-info/WHEEL": "Wheel-Version: 1.0\nGenerator: agentainer-tests\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    "fixture_uv-1.0.dist-info/entry_points.txt": "[console_scripts]\nfixture-uv = fixture_uv:main\n",
}
record = []
with zipfile.ZipFile("fixture_uv-1.0-py3-none-any.whl", "w") as z:
    for name, text in files.items():
        data = text.encode()
        z.writestr(name, data)
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        record.append("%s,sha256=%s,%d" % (name, digest, len(data)))
    record.append("fixture_uv-1.0.dist-info/RECORD,,")
    z.writestr("fixture_uv-1.0.dist-info/RECORD", "\n".join(record) + "\n")
EOF
echo "$d"
