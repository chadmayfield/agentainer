# Troubleshooting

**`sudo: The "no new privileges" flag is set, which prevents sudo from running as root.`**
sudo is off by default. Recreate the container with `bin/agentainer up --sudo`, or leave out `--security-opt no-new-privileges=true` from a raw `docker run` or `podman run` ([docs/running.md](running.md#sudo)).

**`ping: socket: Operation not permitted`**
The container was started without `--sysctl "net.ipv4.ping_group_range=1000 1000"`. The launcher and the Kubernetes example set it; add it to raw `run` commands.

**The container name `agentainer` is already in use**
A container with that name exists. If it is running, `bin/agentainer attach` connects to it. If it is stopped, `bin/agentainer start` starts it, and `bin/agentainer down` removes it. The home volume stays either way.

**`agentainer: ... no option labels`** when running `agentainer update`
The container was not created by `agentainer up`, so `update` does not know its options. Run `bin/agentainer down` and `bin/agentainer up` once.

**Files in `/workspace` belong to UID 1000 on a Linux host.**
That is rootful Docker with a host UID other than 1000. Build an image with your UID, or use Podman or rootless Docker ([docs/running.md](running.md#file-ownership)).

**An agent shows an old setting after an upgrade.**
The entrypoint never overwrites files in your home volume, so new default settings in the image do not replace yours. Compare your files with the image's copies in `/etc/agentainer/home/` ([docs/running.md](running.md#upgrading)).

**`agentainer-mcp` warns that an agent "already has a server named ... that agentainer did not add".**
That agent's own config has a server with the same name, which the sync leaves alone. Rename one of them in `~/.agentainer/mcp.json` or in the agent.

**The tmux session does not start over SSH in Kubernetes: "open terminal failed: terminal does not support clear".**
tmux needs `TERM`. The webhook in `deploy/kubernetes` sets it; check that ContainerSSH uses that webhook's `/config` answer ([docs/kubernetes.md](kubernetes.md#logging-in)).
