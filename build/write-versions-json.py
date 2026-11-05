"""Writes /etc/agentainer/versions.json from versions.env, dpkg and the apt source record. Runs at build time."""
import json
import os
import subprocess

APT_SOURCE = "/usr/local/share/agentainer/apt-source"


def read_apt_source(path):
    """The one line build/apt-install.sh wrote, or "unknown" if the file is missing."""
    try:
        with open(path) as f:
            return f.readline().strip() or "unknown"
    except OSError:
        return "unknown"


def main(versions_env="/usr/local/share/agentainer/versions.env", out_dir="/etc/agentainer", apt_source=APT_SOURCE):
    pins = {}
    with open(versions_env) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                pins[k] = v
    out = subprocess.check_output(["dpkg-query", "-W", "-f", "${Package} ${Version}\n"], universal_newlines=True)
    apt = dict(line.split(" ", 1) for line in out.splitlines() if " " in line)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "versions.json"), "w") as f:
        json.dump({"pins": pins, "apt": apt, "apt_source": read_apt_source(apt_source)}, f, indent=2, sort_keys=True)
        f.write("\n")


if __name__ == "__main__":
    main()
