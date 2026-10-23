"""Check port arguments and update preservation without starting an engine."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PREFIX = "io.github.chadmayfield.agentainer."


class LauncherPortTests(unittest.TestCase):
    def invoke(self, arguments, engine_name="podman", ports=None):
        with tempfile.TemporaryDirectory(prefix="cx-launcher-ports-") as directory:
            base = Path(directory)
            workspace = base / "work space"
            workspace.mkdir()
            labels = {"image": "example.com/agentainer:test", "dir": str(workspace),
                      "sudo": "0", "home": "cx-home", "env-file": ""}
            if ports is not None:
                labels["ports"] = ports
            engine = base / engine_name
            engine.write_text("#!" + sys.executable + "\n" + '''import json,os,sys
from pathlib import Path
base=Path(os.environ['CX_PORT_BASE']); a=sys.argv[1:]
with (base/'calls').open('a') as f:f.write(json.dumps(a)+'\\n')
if a[0]=='inspect':
    if a[-1].startswith('cx-agentainer-backup-'):sys.exit(1)
    fmt=a[a.index('--format')+1]
    if '.State.Running' in fmt:print('true')
    elif '.Id' in fmt:print('cx-original-id')
    else:
        key=fmt.split('agentainer.',1)[1].split('"',1)[0]
        print(json.loads(os.environ['CX_PORT_LABELS']).get(key,''))
''')
            engine.chmod(0o755)
            args = [str(workspace) if arg == "WORKSPACE" else arg for arg in arguments]
            result = subprocess.run(["sh", str(ROOT / "bin/agentainer"), *args],
                                    env=dict(os.environ, AGENTAINER_RUNTIME=str(engine),
                                             AGENTAINER_ENV_FILE="/cx-no-env-file",
                                             AGENTAINER_IMAGE="ghcr.io/chadmayfield/agentainer:latest",
                                             AGENTAINER_HOME_VOLUME="cx-home", AGENTAINER_DRY_RUN="0",
                                             CX_PORT_BASE=str(base), CX_PORT_LABELS=json.dumps(labels)),
                                    capture_output=True, text=True)
            calls = [json.loads(line) for line in (base / "calls").read_text().splitlines()] if (base / "calls").exists() else []
            return result, calls

    def mappings(self, calls):
        create = next(call for call in calls if call[0] == "run")
        return [create[index + 1] for index, value in enumerate(create) if value == "--publish"]

    def test_no_ports_are_published_without_an_option(self):
        result, calls = self.invoke(["up", "WORKSPACE"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.mappings(calls), [])

    def test_repeatable_ports_default_to_loopback_for_both_engines(self):
        for engine in ("podman", "docker"):
            with self.subTest(engine=engine):
                result, calls = self.invoke(["up", "--publish", "3000:3000", "-p", "8080:80/udp", "WORKSPACE"], engine)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.mappings(calls), ["127.0.0.1:3000:3000/tcp", "127.0.0.1:8080:80/udp"])
                create = next(call for call in calls if call[0] == "run")
                self.assertIn(PREFIX + "ports=127.0.0.1:3000:3000/tcp,127.0.0.1:8080:80/udp", create)
                self.assertEqual(create[-1], "ghcr.io/chadmayfield/agentainer:latest")

    def test_explicit_bind_address_and_attached_option_values(self):
        result, calls = self.invoke(["up", "--publish=0.0.0.0:8080:80", "-p9000:9000/tcp", "WORKSPACE"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.mappings(calls), ["0.0.0.0:8080:80/tcp", "127.0.0.1:9000:9000/tcp"])

    def test_port_bounds_and_other_up_options_are_preserved(self):
        result, calls = self.invoke(["up", "-p", "00001:65535/udp", "--sudo", "--name", "cx-project",
                                     "--image", "example.com/custom:1", "--publish", "65535:00001", "WORKSPACE"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.mappings(calls), ["127.0.0.1:1:65535/udp", "127.0.0.1:65535:1/tcp"])
        create = next(call for call in calls if call[0] == "run")
        self.assertEqual(create[-1], "example.com/custom:1")
        self.assertEqual(create[create.index("--name") + 1], "cx-project")
        self.assertNotIn("no-new-privileges=true", create)
        self.assertTrue(any(value.endswith("work space:/workspace") for value in create))

    def test_invalid_mappings_never_call_the_engine(self):
        for value in ("", "80", "0:80", "65536:80", "80:0", "80:65536", "-1:80", "80:abc",
                      ":80:80", "999.1.1.1:80:80", "localhost:80:80", "80:80/sctp", "80:80/tcp/udp",
                      "80-81:80-81", "[::1]:80:80", "80:80 --privileged", "80:80,81:81", "80:80\n81:81",
                      "$(id):80", "80:80\\n81:81"):
            with self.subTest(value=value):
                result, calls = self.invoke(["up", "--publish", value, "WORKSPACE"])
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])

    def test_missing_mapping_is_rejected(self):
        result, calls = self.invoke(["up", "--publish"])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_update_reuses_recorded_ports_for_both_engines(self):
        mappings = "127.0.0.1:3000:3000/tcp,0.0.0.0:5353:53/udp"
        for engine in ("podman", "docker"):
            with self.subTest(engine=engine):
                result, calls = self.invoke(["update", "cx-example"], engine, mappings)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.mappings(calls), mappings.split(","))
                create = next(call for call in calls if call[0] == "run")
                self.assertIn(PREFIX + "ports=" + mappings, create)

    def test_update_of_legacy_container_publishes_nothing(self):
        for label in (None, "", "<no value>"):
            with self.subTest(label=label):
                result, calls = self.invoke(["update", "cx-example"], ports=label)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.mappings(calls), [])

    def test_invalid_recorded_ports_leave_container_untouched(self):
        for label in ("80:80,", ",80:80", "80:80,,81:81", "127.0.0.1:0:80/tcp", "--privileged"):
            with self.subTest(label=label):
                result, calls = self.invoke(["update", "cx-example"], ports=label)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(calls)
                self.assertTrue(all(call[0] == "inspect" for call in calls))
