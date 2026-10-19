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
The entrypoint adds the image's files only where your home volume has none, so new default settings in the image do not replace yours. Compare your files with the image's copies in `/etc/agentainer/home/` ([docs/running.md](running.md#upgrading)). A few files are exceptions, and the entrypoint changes only the part it manages in each: `~/.agentainer/AGENTS.md` while you have not edited it ([AGENTS.md](configuration.md#agentsmd)), the MCP servers that `agentainer-mcp sync` added ([MCP servers](configuration.md#mcp-servers)), the gh credential helper in `~/.gitconfig` when `GH_TOKEN` or `GITHUB_TOKEN` is set, the git identity when `GIT_AUTHOR_NAME` or `GIT_AUTHOR_EMAIL` is set and `~/.gitconfig` has none, and `~/.config/opencode/service.json` when it does not exist yet.

**`claude doctor` warns that `~/.local/bin` is not in `PATH` and says to run `claude install`.**
The image installs Claude Code at `/usr/local/bin/claude`, and a new image brings a new version. The warnings look for Anthropic's per-user install in `~/.local`, which the image does not use. Ignore them: `claude install` prints "Updates are disabled by your administrator" and changes nothing.

**`agentainer-mcp` warns that an agent "already has a server named ... that agentainer did not add".**
That agent's own config has a server with the same name, which the sync leaves alone. Rename one of them in `~/.agentainer/mcp.json` or in the agent.

**The tmux session does not start over SSH in Kubernetes: "open terminal failed: terminal does not support clear".**
tmux needs `TERM`. The webhook in `deploy/kubernetes` sets it; check that ContainerSSH uses that webhook's `/config` answer ([docs/kubernetes.md](kubernetes.md#logging-in)).
