# Running Agentainer with Podman or Docker

## The launcher

[`bin/agentainer`](../bin/agentainer) wraps the `run` and `exec` commands below. It uses Podman when it finds it, otherwise Docker, and prints each command before it runs it.

| Command | What it does |
|---|---|
| `agentainer up [--name N] [--sudo] [--image I] [--] [DIR]` | Starts a detached container. DIR defaults to the current directory and becomes `/workspace`. |
| `agentainer attach [N]` | Runs `tmux new-session -A -s main` in the container |
| `agentainer shell [N]` | Opens a bash login shell |
| `agentainer start [N]` | Starts a stopped container, for example after the host or the Podman machine restarts |
| `agentainer update [N]` | Pulls the image the container was created from and recreates the container with the same options |
| `agentainer down [N]` | Removes the container. The home volume stays. |
| `agentainer status` | Lists agentainer containers |

N defaults to `agentainer`. These variables override the launcher's defaults:

| Variable | Default |
|---|---|
| `AGENTAINER_IMAGE` | `ghcr.io/chadmayfield/agentainer:latest` |
| `AGENTAINER_ENV_FILE` | `~/.config/agentainer/env` |
| `AGENTAINER_HOME_VOLUME` | `agentainer-home` |
| `AGENTAINER_RUNTIME` | `podman` if installed, else `docker` |

`up` records its options (DIR, image, sudo setting, home volume and the env file's absolute path) as container labels, and `update` reads them back:

- `update` changes nothing when the pull fails, when DIR or the env file no longer exists, or when the container was not made by `up`.
- `update` pulls from a registry, so it cannot update a container that runs an image you built locally (`localhost/...`). Use `agentainer down` and `agentainer up --image ...` for those.
- DIR must not contain `:`, because `-v` splits its value at `:`. Use a symlink without `:` instead.

## Without the launcher

```sh
docker run -d --name agentainer --hostname agentainer \
  --security-opt no-new-privileges=true \
  --sysctl "net.ipv4.ping_group_range=1000 1000" \
  -v agentainer-home:/home/agent \
  -v "$HOME/code:/workspace" -w /workspace \
  --env-file "$HOME/.config/agentainer/env" \
  ghcr.io/chadmayfield/agentainer:latest
docker exec -it agentainer tmux new-session -A -s main
```

With Podman, use the same commands and add `--userns=keep-id:uid=1000,gid=1000`. It maps your host user to the container user, so files in `/workspace` stay yours (`man podman-run`).

- The container runs `sleep infinity` under `tini` as PID 1. Sessions are `exec` calls into tmux, so agents keep running when a terminal or SSH connection drops.
- The whole home directory `/home/agent` is one volume. Logins, settings and `AGENTS.md` live there and survive a new container. Containers that use the same volume share logins, and two containers running the same agent write the same files.
- The `ping_group_range` sysctl lets `ping` work without the `NET_RAW` capability. It names only GID 1000: with Podman's keep-id the GID map is not contiguous, and a wider range breaks.

## sudo

The image has passwordless sudo, and `--security-opt no-new-privileges=true` turns it off ([Docker reference](https://docs.docker.com/reference/cli/docker/container/run/)). `agentainer up --sudo` leaves that option out.

With sudo on, an agent can change anything in the container, including the agent binaries and the settings that stop them from updating themselves. Packages installed with `sudo apt install` are gone when the container is recreated. Under rootful Docker, container root is UID 0 on the host, limited by the container's namespaces.

## File ownership

- Rootless Podman with keep-id: files in `/workspace` belong to your host user.
- Rootful Docker on Linux: files written to `/workspace` belong to UID 1000 on the host. If your UID is different, build your own image with `scripts/build.sh --uid "$(id -u)" --gid "$(id -g)"`, or use Podman or rootless Docker. With a GID other than 1000, also change the `ping_group_range` value to `"<gid> <gid>"` in your `run` command, or `ping` fails; the launcher always passes `1000 1000`.

## Other options

- SSH agent on a Linux host: add `-v "$SSH_AUTH_SOCK:/run/ssh-agent.sock" -e SSH_AUTH_SOCK=/run/ssh-agent.sock`. CI checks this on a Linux runner. On macOS the socket path depends on the runtime; this is not verified. For git, the default is `GH_TOKEN` ([docs/logins.md](logins.md)).
- SELinux hosts may need `:z` on volume mounts. Not verified.

## Upgrading

```sh
bin/agentainer update
```

`update` pulls the image the container was created from and recreates the container; the home volume stays. Without the launcher, pull first: a plain `run` does not pull a newer `latest` if an older one is already on your machine. For Kubernetes, see [docs/kubernetes.md](kubernetes.md#upgrading-and-removing).

On the first start of the new image, the entrypoint adds files that are missing from your home volume and does not replace your files with the image's copies:

- Logins, agent settings and history stay.
- New defaults in the image's seed files do not reach an existing home. The image's copies are in `/etc/agentainer/home/` (for example `.claude/settings.json` and `.codex/config.toml`) if you want to compare them with yours.
- `~/.agentainer/AGENTS.md` follows the new default only if you never edited it ([docs/configuration.md](configuration.md#agentsmd)).
- With `AGENTAINER_TOOLS=persist`, tools you installed stay on `PATH` after the image's own tools. The entrypoint warns on each start until you run `agentainer-tools reset`, which moves them to a dated backup.
- MCP servers sync again only when `~/.agentainer/mcp.json` changes. Run `agentainer-mcp sync` to sync after an upgrade.
- Anything installed with `sudo apt install` is gone, as after every new container.
