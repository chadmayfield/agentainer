#!/usr/bin/env python3
"""Exercise image health metadata and engine transitions in one disposable container."""
import json
import os
import subprocess
import sys
import time
import uuid


def main():
    runtime = os.environ.get("RUNTIME", "podman")
    image = os.environ.get("IMAGE", "localhost/agentainer:dev")
    name = "cx-health-" + uuid.uuid4().hex[:12]
    created = False
    count = 0

    def run(*args, expected=0):
        result = subprocess.run([runtime, *args], capture_output=True, text=True, timeout=30)
        if expected is not None and result.returncode != expected:
            raise AssertionError("engine command failed: " + args[0])
        return result

    def passed(message):
        nonlocal count
        count += 1
        print("ok", count, "-", message, flush=True)

    def health():
        return json.loads(run("inspect", name).stdout)[0]["State"]["Health"]

    def wait_for(predicate):
        deadline = time.monotonic() + 45
        last = {}
        while time.monotonic() < deadline:
            last = health()
            if predicate(last):
                return
            time.sleep(0.25)
        logs = last.get("Log") or []
        raise AssertionError("health transition timed out: status=" + str(last.get("Status"))
                             + ", last exit=" + str(logs[-1]["ExitCode"] if logs else None))

    def execute(script):
        return run("exec", name, "sh", "-ec", script)

    try:
        inspected = json.loads(run("image", "inspect", image).stdout)[0]
        # Docker nests this under Config; Podman's image inspect uses a top-level field.
        metadata = inspected["Config"].get("Healthcheck") or inspected.get("Healthcheck")
        assert metadata, "image has no health check"
        assert metadata["Test"] == ["CMD", "/usr/local/bin/agentainer-healthcheck"], "wrong health command"
        for key, value in (("Interval", 30_000_000_000), ("Timeout", 5_000_000_000),
                           ("StartPeriod", 180_000_000_000), ("Retries", 3)):
            assert metadata[key] == value, "wrong health setting: " + key
        passed("image defines the offline probe and startup grace")
        # Delay the real entrypoint until a failed probe has exercised startup grace.
        # A short grace period avoids a three-minute wait in the test.
        command = ('while [ ! -f /var/lib/agentainer/cx-health-release ]; do sleep 0.1; done; '
                   'exec /usr/local/bin/agentainer-entrypoint sleep infinity')
        # Supply command and timing together so older Podman versions retain the
        # shortened test schedule rather than restoring the image's timing defaults.
        created = True
        run("run", "-d", "--name", name, "--pull=never", "--network", "none",
            "--health-cmd=" + metadata["Test"][1], "--health-interval=1s",
            "--health-start-period=20s", "--health-retries=2", "--entrypoint", "/bin/sh",
            image, "-ec", command)
        wait_for(lambda h: h["Status"] == "starting" and h.get("Log")
                 and h["Log"][-1]["ExitCode"] == 1 and h["FailingStreak"] == 0)
        passed("failed startup probes remain starting during grace")
        execute(": >/var/lib/agentainer/cx-health-release")
        wait_for(lambda h: h["Status"] == "healthy")
        passed("completed startup becomes healthy automatically")
        execute("mv /var/lib/agentainer/active /var/lib/agentainer/cx-active")
        wait_for(lambda h: h["Status"] == "unhealthy")
        passed("missing tools become unhealthy after repeated failures")
        execute("mv /var/lib/agentainer/cx-active /var/lib/agentainer/active")
        wait_for(lambda h: h["Status"] == "healthy")
        passed("restored tools recover automatically")
        execute('chmod 500 "$HOME"')
        wait_for(lambda h: h["Status"] == "unhealthy")
        execute('chmod 700 "$HOME"')
        wait_for(lambda h: h["Status"] == "healthy")
        passed("home permission failures are detected and recover")
        result = run("exec", "-e", "HOME=/cx-private-value", name,
                     "/usr/local/bin/agentainer-healthcheck", expected=1)
        assert "cx-private-value" not in result.stdout + result.stderr, "private path leaked"
        passed("failure output omits environment values")
    except (AssertionError, KeyError, ValueError, OSError, subprocess.SubprocessError) as error:
        print("not ok", count + 1, "-", str(error), flush=True)
        return 1
    finally:
        if created and run("container", "inspect", name, expected=None).returncode == 0:
            result = run("rm", "-f", name, expected=None)
            if result.returncode:
                raise RuntimeError("could not remove disposable health-check container")
    print("1.." + str(count))
    return 0


if __name__ == "__main__":
    sys.exit(main())
