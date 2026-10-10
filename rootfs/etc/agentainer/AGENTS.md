# Agentainer environment

You are running inside an Agentainer container.

- Your code is in `/workspace`. That is the only folder shared with the host or kept on a workspace volume.
- Your home is `/home/agent`. It persists across restarts.
- `sudo` is usually disabled. If it works, packages installed with `apt` are lost when the container is recreated (for example on an image upgrade).
- Install extra tools in user space: `uv tool install`, `pipx install`, `npm install -g`, `cargo install` or `go install`. They go to `/var/lib/agentainer/active`. Whether they survive the container being recreated depends on `AGENTAINER_TOOLS` (`ephemeral` or `persist`).
- Python refuses `pip install --user` here (PEP 668). Use `uv`, `pipx` or a virtual environment.
- Credentials may come from environment variables or from agent login files in your home. Never print them, copy them into other files, or commit them.
- Commit and push work often. In Kubernetes, unpushed work exists only on the workspace volume.

Edit this file to add your own instructions. It is `~/.agentainer/AGENTS.md`, and every agent in this container reads it.
