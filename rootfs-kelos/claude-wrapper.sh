#!/bin/bash -p
# Installed as /usr/local/lib/kelos/bin/claude, ahead of the real binary on PATH
# while the dispatcher runs the Kelos entrypoint. The entrypoint writes files
# before it starts claude, so the guard runs here, right before the agent starts.
# The real claude then starts by absolute path under env -i with only the
# variables in claude_env_allowlist (kelos_guard.sh), so a variable the guard
# does not know about, such as BUN_OPTIONS, never reaches it.
set -uo pipefail
# shellcheck disable=SC1091 # exists in the image
. /usr/local/lib/kelos/guard.sh
kelos_preflight
claude_guard

kept=(PATH=/home/kelos/.local/bin:/usr/local/go/bin:/opt/cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin)
# shellcheck disable=SC2154 # defined in kelos_guard.sh
for name in "${claude_env_allowlist[@]}"; do
  if [ -n "${!name+x}" ]; then
    kept+=("$name=${!name}")
  fi
done
# env -i drops HOME too; fall back to the image user's home when the pod has none.
[ -n "${HOME:-}" ] || kept+=(HOME=/home/kelos)
# --setting-sources user: load only the image's user settings, never the
# cloned repo's .claude/settings.json or settings.local.json, whose env block
# could swap the credential and whose hooks run before the first prompt.
# --strict-mcp-config: ignore the repo's .mcp.json servers for the same reason;
# only the gateway file below, when there is one, is read.
# --setting-sources user also stops the repo's CLAUDE.md from loading, so a
# regular-file CLAUDE.md in the working directory (the cloned repo) is passed
# as prompt text instead: its rules apply, its settings never do.
extra=()
if [ -f ./CLAUDE.md ] && [ ! -L ./CLAUDE.md ]; then
  extra=(--append-system-prompt-file "$PWD/CLAUDE.md")
fi
# MCP gateway: kelos_preflight has checked the mounted url and token files and
# set mcp_url when both are present. The config names the URL and the header
# helper, never the token; the helper reads the token file each time Claude
# connects. $HOME/.claude is in the image layer, so the file is new in each pod.
# shellcheck disable=SC2154 # set by mcp_check in kelos_guard.sh
if [ -n "$mcp_url" ]; then
  mcp_config=$HOME/.claude/mcp-gateway.json
  # shellcheck disable=SC2016 # $u is a jq variable
  # Remove first, so a link left at that path is replaced and not followed.
  if ! (umask 077 && /usr/bin/rm -f -- "$mcp_config" && "$JQ" -n --arg u "$mcp_url" \
    '{mcpServers: {gateway: {type: "http", url: $u, headersHelper: "/usr/local/lib/kelos/mcp-headers"}}}' >"$mcp_config"); then
    refuse "cannot write $mcp_config"
  fi
  extra=(--mcp-config "$mcp_config" "${extra[@]}")
fi
exec /usr/bin/env -i "${kept[@]}" /usr/local/bin/claude --setting-sources user --strict-mcp-config "${extra[@]}" "$@"
