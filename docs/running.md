# Running Agentainer with Podman or Docker

## Contents

- [The launcher](#the-launcher)
- [Development server ports](#development-server-ports)
- [Without the launcher](#without-the-launcher)
- [Container health](#container-health)
- [sudo](#sudo)
- [File ownership](#file-ownership)
- [Other options](#other-options)
- [Upgrading](#upgrading)

## The launcher

[`bin/agentainer`](../bin/agentainer) wraps the `run` and `exec` commands below. It uses Podman when it finds it, otherwise Docker, and prints each command before it runs it.

| Command | What it does |
|---|---|
| `agentainer up [--name N] [--sudo] [--image I] [--publish MAPPING ...] [--] [DIR]` | Starts a detached container. DIR defaults to the current directory and becomes `/workspace`. |
| `agentainer attach [N]` | Runs `tmux new-session -A -s main` in the container |
| `agentainer shell [N]` | Opens a bash login shell |
| `agentainer start [N]` | Starts a stopped container, for example after the host or the Podman machine restarts |
| `agentainer update [N]` | Pulls the image the container was created from and recreates the container with the same options |
| `agentainer down [N]` | Removes the container. The home volume stays. |
| `agentainer status` | Lists agentainer containers |
| `agentainer doctor [N] [--json]` | Runs offline diagnostics in the running container, without a TTY; see [diagnostic checks and exit codes](troubleshooting.md#offline-diagnostics). |

N defaults to `agentainer`. These variables override the launcher's defaults:

| Variable | Default |
|---|---|
| `AGENTAINER_IMAGE` | `ghcr.io/chadmayfield/agentainer:latest` |
| `AGENTAINER_ENV_FILE` | `~/.config/agentainer/env` |
| `AGENTAINER_HOME_VOLUME` | `agentainer-home` |
| `AGENTAINER_RUNTIME` | `podman` if installed, else `docker` |

For a host directory instead of the default named home volume, set `AGENTAINER_HOME_VOLUME` to an existing directory such as `"$HOME/.config/agentainer/home"`. Both mount at `/home/agent`. [Customizing Agentainer](customization.md) covers setup, your own dotfiles and separate test homes.

`up` records its options (DIR, image, sudo setting, home volume, published ports and the env file's absolute path) as container labels, and `update` reads them back:

- `update` changes nothing when the pull fails, when DIR or the env file no longer exists, or when the container was not made by `up`.
- After pulling, `update` renames the previous container to `cx-agentainer-backup-N` and stops it. It removes that backup only after replacement startup succeeds. A creation or startup failure restores the previous container and its running or stopped state. Home and workspace changes made by the replacement are not rolled back.
- Startup may take up to 180 seconds. New images signal entrypoint completion; older images fall back to checking the tools link. If the launcher is killed before it can restore a failed update, inspect `cx-agentainer-backup-N` before retrying. It refuses to overwrite an existing backup. These operations use [Docker rename](https://docs.docker.com/reference/cli/docker/container/rename/) and [Podman rename](https://docs.podman.io/en/latest/markdown/podman-rename.1.html).
- `update` pulls from a registry, so it cannot update a container that runs an image you built locally (`localhost/...`). Use `agentainer down` and `agentainer up --image ...` for those.
- DIR must not contain `:`, because `-v` splits its value at `:`. Rename the directory to remove `:`.

## Development server ports

Repeat `--publish` or `-p` before DIR to publish development servers to the host:

```sh
bin/agentainer up --publish 3000:3000 --publish 8080:8000 "$HOME/code"
```

Each mapping is `[IPv4:]HOST_PORT:CONTAINER_PORT[/tcp|udp]`. Omitting the address selects `127.0.0.1`, and omitting the protocol selects TCP. The example maps host ports 3000 and 8080 to container ports 3000 and 8000. Open `http://127.0.0.1:8080` on the host for a server listening on container port 8000. The server must listen on the container's network interface, for example `0.0.0.0`, rather than only its own loopback address ([Docker publishing](https://docs.docker.com/engine/network/port-publishing/), [Podman publishing](https://docs.podman.io/en/latest/markdown/podman-run.1.html)).

For UDP, use a mapping such as `--publish 5353:5353/udp`. An explicit bind address changes host access; `--publish 0.0.0.0:3000:3000` binds all host IPv4 interfaces. For a remote engine, the bind address belongs to the engine host. With a local VM, reachability also depends on the runtime's port forwarding.

The launcher accepts individual ports from 1 through 65535 and optional numeric IPv4 addresses. IPv6, port ranges and automatically assigned host ports require a direct runtime command. `--publish=3000:3000` and `-p3000:3000` are also accepted. It validates mappings before creating a container and validates recorded mappings before pulling an update. `update` keeps the mappings; a restored backup retains its own original mapping. Containers created by older launchers without a ports label continue to publish no ports.

With no `--publish` option, the launcher publishes no ports. Change the mappings by recreating the container with the desired `up` options; the persistent home stays in place.

## Without the launcher

Before the first stable release, replace `:latest` in the command below with an available prerelease tag, such as `:0.1.0-dev.20261019.1`. The registry has no `latest` manifest until a stable release publishes it ([release policy](versions.md#releases)).

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

## Container health

The image runs [`agentainer-healthcheck`](../rootfs/usr/local/bin/agentainer-healthcheck) every 30 seconds, with a five-second timeout, a 180-second startup grace period and three consecutive failures before `unhealthy`. These settings use the [Dockerfile `HEALTHCHECK` instruction](https://docs.docker.com/reference/dockerfile/#healthcheck), supported by [Podman](https://docs.podman.io/en/v5.3.2/markdown/podman-run.1.html#health-start-period-period).

The probe checks the entrypoint's completion marker, home-directory read/write/search permissions and the active tools symlink's readable, searchable directory target. Startup clears the previous marker, including after a container restart. The probe reads no agent settings or credentials, runs no agents, changes no home files and makes no network requests. It checks access permissions, not whether the disk has free space or every tool works. Use [`agentainer doctor`](troubleshooting.md#offline-diagnostics) for broader diagnostics.

Inspect the status and recent probe results from the host:

```sh
podman inspect --format '{{json .State.Health}}' agentainer
docker inspect --format '{{json .State.Health}}' agentainer
```

Health status reports readiness; it does not restart the container automatically. Docker ends startup grace after the first successful probe; Podman 5.3.2 continues suppressing failure counts until the grace deadline ([Podman source](https://github.com/containers/podman/blob/v5.3.2/libpod/healthcheck.go#L127-L136)). Older published images without this check require an image update and container recreation. Kubernetes does not use image health checks; pod probes must be configured separately ([Kubernetes probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)).

## sudo

The image has passwordless sudo, and `--security-opt no-new-privileges=true` turns it off ([Docker reference](https://docs.docker.com/reference/cli/docker/container/run/)). `agentainer up --sudo` leaves that option out.

With sudo on, an agent can change anything in the container, including the agent binaries and the settings that stop them from updating themselves. Packages installed with `sudo apt install` are gone when the container is recreated. Under rootful Docker, container root is UID 0 on the host, limited by the container's namespaces.

## File ownership

- Rootless Podman with keep-id: files in `/workspace` belong to your host user.
- Rootful Docker on Linux: files written to `/workspace` belong to UID 1000 on the host. If your UID is different, build your own image with `scripts/build.sh --uid "$(id -u)" --gid "$(id -g)"`, or use Podman or rootless Docker. With a GID other than 1000, also change the `ping_group_range` value to `"<gid> <gid>"` in your `run` command, or `ping` fails; the launcher always passes `1000 1000`.

## Other options

- SSH agent on a Linux host: add `-v "$SSH_AUTH_SOCK:/run/ssh-agent.sock" -e SSH_AUTH_SOCK=/run/ssh-agent.sock`. `ssh-agent` refuses a client whose UID differs from its own unless the client is root (`uid mismatch` in [ssh-agent.c](https://github.com/openssh/openssh-portable/blob/master/ssh-agent.c)), so the container user must have the UID of the user who started the agent:
  - Rootless Podman with keep-id, as the launcher runs it, maps your host UID to the container user ([podman-run](https://docs.podman.io/en/latest/markdown/podman-run.1.html)). Not verified with an SSH agent.
  - Rootful Docker runs the container user as UID 1000. If your UID is different, build your own image with `--uid` as described in [File ownership](#file-ownership).

  CI covers only rootful Docker on an Ubuntu runner. It starts `ssh-agent`, runs `chmod 755` on the socket's directory, and runs `ssh-add -l` as the image's entrypoint with `--user "$(id -u):$(id -g)"`, so the full entrypoint does not run in that check. On macOS the socket path depends on the runtime; this is not verified. For git, the default is `GH_TOKEN` ([docs/logins.md](logins.md)).
- SELinux hosts may need `:z` on volume mounts. Not verified.

## Upgrading

```sh
bin/agentainer update
```

`update` pulls the image the container was created from and recreates the container; the home volume stays. Without the launcher, pull first: a plain `run` does not pull a newer `latest` if an older one is already on your machine. For Kubernetes, see [docs/kubernetes.md](kubernetes.md#upgrading-and-removing).

On the first start of the new image, the entrypoint adds files that are missing from your home volume and does not replace your files with the image's copies. The exceptions are `~/.agentainer/AGENTS.md`, the MCP servers that `agentainer-mcp sync` added, `~/.gitconfig` and `~/.config/opencode/service.json`, as described below.

- Logins, agent settings and history stay.
- When `GH_TOKEN` or `GITHUB_TOKEN` is set, `gh auth setup-git` writes the GitHub credential helper to `~/.gitconfig`, unless this container's `gh` is already the helper. When `GIT_AUTHOR_NAME` or `GIT_AUTHOR_EMAIL` is set and `~/.gitconfig` has no `user.name` or `user.email`, the entrypoint writes that value ([docs/logins.md](logins.md#github-and-git)).
- The OpenCode step runs `opencode service set disabled true` once per home volume, which writes `~/.config/opencode/service.json`.
- New defaults in the image's seed files do not reach an existing home. The image's copies are in `/etc/agentainer/home/` (for example `.claude/settings.json` and `.codex/config.toml`) if you want to compare them with yours.
- `~/.agentainer/AGENTS.md` follows the new default only if you never edited it ([docs/configuration.md](configuration.md#agentsmd)).
- With `AGENTAINER_TOOLS=persist`, tools you installed stay on `PATH` after the image's own tools. The entrypoint warns on each start until you run `agentainer-tools reset`, which moves them to a dated backup.
- MCP servers sync again only when `~/.agentainer/mcp.json` changes. Run `agentainer-mcp sync` to sync after an upgrade.
- Anything installed with `sudo apt install` is gone, as after every new container.
