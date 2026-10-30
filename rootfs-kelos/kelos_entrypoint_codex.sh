#!/bin/bash
# kelos_entrypoint.sh — Kelos agent image interface implementation for
# OpenAI Codex CLI.
#
# Interface contract:
#   - First argument ($1): the task prompt
#   - KELOS_SESSION_SETUP_ONLY=1: prepare configuration and exit without a prompt
#   - KELOS_MODEL env var: model name (optional)
#   - UID 61100: shared between git-clone init container and agent
#   - Working directory: /workspace/repo when a workspace is configured

set -uo pipefail

# AGENTAINER CHANGE 4: start every run with a clean Codex home. The home is a
# persistent volume, so anything a run leaves there (a changed config.toml, extra
# instruction files, hooks, MCP settings, session history) would apply to the next
# run. Every entry except auth.json is removed, dotfiles and subdirectories
# included, before the steps below write config.toml and AGENTS.md. auth.json stays
# because Codex refreshes its login token in that file. Before removing a
# directory, find -P gives the owner rwx on every directory inside it that lacks
# it, so a directory left at mode 500 or 000 does not stop the removal. find -P
# does not follow symlinks and -type d matches only real directories, so no link
# target changes mode, and files keep their mode (a hard link to auth.json keeps
# 0600). GNU rm -rf removes a symlink as a link and does not follow links inside a
# directory it removes. On an ext4 volume this also removes lost+found; the
# filesystem works without it. A lost+found owned by root that holds files cannot
# be removed, and the start then exits 78. The dispatcher exports CODEX_HOME after
# its guard has checked the value. Exit code 78 matches the dispatcher's refusals.
codex_refuse() {
  printf 'kelos_entrypoint_codex: refusing to start: %s\n' "$1" >&2
  exit 78
}
codex_home_reset() {
  local home=/home/kelos/.codex entry
  [ -n "${CODEX_HOME:-}" ] || codex_refuse "CODEX_HOME is not set"
  [ "$CODEX_HOME" = "$home" ] || codex_refuse "CODEX_HOME is $CODEX_HOME, not $home"
  [ ! -L "$home" ] || codex_refuse "$home is a symlink"
  if [ -e "$home" ] && [ ! -d "$home" ]; then
    codex_refuse "$home is not a directory"
  fi
  mkdir -p "$home" || codex_refuse "cannot create $home"
  [ ! -L "$home/auth.json" ] || codex_refuse "$home/auth.json is a symlink"
  if [ -e "$home/auth.json" ] && [ ! -f "$home/auth.json" ]; then
    codex_refuse "$home/auth.json is not a regular file"
  fi
  # A run may have changed the mode of the login file; it is kept at 0600.
  if [ -f "$home/auth.json" ]; then
    chmod 600 -- "$home/auth.json" || codex_refuse "cannot set the mode of $home/auth.json"
  fi
  shopt -s dotglob nullglob
  for entry in "$home"/*; do
    [ "$entry" != "$home/auth.json" ] || continue
    if [ -d "$entry" ] && [ ! -L "$entry" ]; then
      find -P "$entry" -type d ! -perm -u=rwx -exec chmod u+rwx -- {} \; 2>/dev/null
    fi
    rm -rf -- "$entry" || codex_refuse "cannot remove $entry"
  done
  shopt -u dotglob nullglob
}
codex_home_reset

# AGENTAINER CHANGE 5: check an existing auth.json against CODEX_AUTH_JSON. A run
# can leave auth.json invalid or holding another login, and the upstream steps only
# seed a missing file, so every later run would use it. Codex rotates the refresh
# token and writes it back to auth.json, so a file that still holds the same login
# is kept as it is. Prints the reason the file must be replaced, or nothing to keep
# it. Field names are those of AuthDotJson and TokenData in Codex 0.163.0
# (openai/codex rust-v0.163.0, codex-rs/login/src/auth/storage.rs and
# codex-rs/login/src/token_data.rs). A refresh changes only tokens.id_token,
# tokens.access_token, tokens.refresh_token and last_refresh. Codex may also store
# its own agent_identity record for the same account. Every other credential field
# must equal the one in CODEX_AUTH_JSON. A file that passes these checks must also
# load in Codex itself: serde rejects files that jq accepts, such as an id_token
# that is not a JWT or a duplicate key. Only field names are printed, never values.
codex_auth_mismatch() {
  local file=$1 secret reason
  secret=$(printf '%s' "$CODEX_AUTH_JSON" | tr -d '\n\r')
  if ! printf '%s' "$secret" | jq -s -e 'length == 1 and (.[0] | type == "object")' >/dev/null 2>&1; then
    printf 'kelos_entrypoint_codex: CODEX_AUTH_JSON is not a JSON object; auth.json not checked\n' >&2
    return 0
  fi
  if ! jq -s -e 'length == 1 and (.[0] | type == "object")' "$file" >/dev/null 2>&1; then
    echo "it is not a single JSON object"
    return 0
  fi
  # shellcheck disable=SC2016 # $s and $f are jq variables
  reason=$({ printf '%s\n' "$secret" && cat -- "$file"; } | jq -r -n '
    def nonempty: type == "string" and length > 0;
    input as $s | input as $f |
    if ($f.tokens | type) != "object"
      or ([$f.tokens.id_token, $f.tokens.access_token, $f.tokens.refresh_token] | all(nonempty) | not)
    then "it lacks tokens.id_token, tokens.access_token or tokens.refresh_token"
    elif ($f.tokens.account_id // null) != ($s.tokens.account_id? // null)
    then "its tokens.account_id differs from CODEX_AUTH_JSON"
    else
      (["auth_mode", "OPENAI_API_KEY", "personal_access_token", "bedrock_api_key", "bedrock_access_keys"]
        | map(select(($f[.] // null) != ($s[.] // null)))) as $diff
      | if ($diff | length) > 0 then "its \($diff | join(", ")) differs from CODEX_AUTH_JSON"
        elif ($f.agent_identity // null) != null
          and $f.agent_identity != ($s.agent_identity // null)
          and (($f.agent_identity | type) != "object"
            or ($f.agent_identity.account_id // null) != ($s.tokens.account_id? // null))
        then "its agent_identity is not for the CODEX_AUTH_JSON account"
        else empty end
    end' 2>/dev/null) || reason="it could not be checked"
  if [ -n "$reason" ]; then
    echo "$reason"
    return 0
  fi
  codex_auth_loads "$file"
}

# Logs that the load check could not run. The file is kept: Codex treats a reused
# refresh token as a hard failure (refresh_token_reused in
# codex-rs/login/src/auth/manager.rs, Codex 0.163.0), so replacing a login that has
# rotated its refresh token could lock it out, while keeping a bad file costs one
# failed run.
codex_auth_unchecked() {
  printf 'kelos_entrypoint_codex: could not check auth.json, kept the existing file: %s\n' "$1" >&2
}

# Runs "codex login status" on a copy of the file, in a private directory, so that
# Codex writes nothing into the real home (it creates a tmp directory there). Prints
# a reason only when Codex itself rejects the file. A timeout, an exit status from
# timeout itself (125 when it fails, 126 or 127 when codex cannot run), or a failure
# to make the directory or the copy keeps the file. In
# Codex 0.163.0 (codex-rs/cli/src/login.rs, run_login_status) the command loads
# auth.json through AuthConfig::load_auth and exits. For a ChatGPT login,
# CodexAuth::from_auth_dot_json (codex-rs/login/src/auth/manager.rs) builds the
# client without sending a request, and no token refresh runs. The agent identity
# and personal access token modes do send requests; the checks above only let them
# through when CODEX_AUTH_JSON uses the same mode, and timeout stops the command
# after 20 s. The workload identity variables are removed because they switch the
# command to a different, networked path (login/src/auth/workload_identity.rs).
codex_auth_loads() {
  local dir rc
  if ! dir=$(mktemp -d "${TMPDIR:-/tmp}/codex-auth-check.XXXXXX" 2>/dev/null); then
    codex_auth_unchecked "cannot create a directory for the check"
    return 0
  fi
  if ! (umask 077 && cp -- "$1" "$dir/auth.json" 2>/dev/null); then
    rm -rf -- "$dir"
    codex_auth_unchecked "cannot copy auth.json for the check"
    return 0
  fi
  env -u OPENAI_FEDERATION_RULE_ID -u OPENAI_IDENTITY_TOKEN_FILE -u OPENAI_WORKLOAD_IDENTITY_CONTEXT \
    CODEX_HOME="$dir" timeout -k 5 20 codex login status </dev/null >/dev/null 2>&1
  rc=$?
  rm -rf -- "$dir"
  case "$rc" in
  0) ;;
  124 | 137) codex_auth_unchecked "codex login status did not finish within 20 s" ;;
  125 | 126 | 127) codex_auth_unchecked "codex login status could not run (exit $rc)" ;;
  *) echo "codex login status rejects it (exit $rc)" ;;
  esac
}

codex_home="${CODEX_HOME:-$HOME/.codex}"
mkdir -p "$codex_home"
if [ "${KELOS_SESSION_SETUP_ONLY:-}" = "1" ]; then
  : >"$codex_home/config.toml"
fi

# Write auth.json from env var for OAuth/ChatGPT credential flow.
# Strip control characters so serde_json's strict parser accepts
# the file (the env var value may contain raw newlines).
if [ -n "${CODEX_AUTH_JSON:-}" ]; then
  # AGENTAINER CHANGE: write auth.json only when it is missing. Upstream
  # always overwrites it, which would replace a token that Codex refreshed
  # on the persistent volume with the older value from the Secret.
  # AGENTAINER CHANGE 2: create auth.json with mode 0600 (umask set before the
  # file exists), so the token is not world-readable.
  if [ ! -e "$codex_home/auth.json" ]; then
    (
      umask 077
      printf '%s' "$CODEX_AUTH_JSON" | tr -d '\n\r' >"$codex_home/auth.json"
    )
  # AGENTAINER CHANGE 5: replace an existing auth.json that is invalid or holds
  # another login. The new file is written beside it with mode 0600 and renamed
  # over it.
  elif reason=$(codex_auth_mismatch "$codex_home/auth.json") && [ -n "$reason" ]; then
    printf 'kelos_entrypoint_codex: reseeded auth.json from CODEX_AUTH_JSON because %s\n' "$reason" >&2
    (
      umask 077
      tmp=$(mktemp "$codex_home/.auth.json.XXXXXX") &&
        printf '%s' "$CODEX_AUTH_JSON" | tr -d '\n\r' >"$tmp" &&
        mv -f -- "$tmp" "$codex_home/auth.json"
    ) || codex_refuse "cannot replace $codex_home/auth.json"
  fi
  # AGENTAINER CHANGE 3: add the setting only when it is absent. Upstream appends
  # it on every start, and a second start on a persistent home leaves a duplicate
  # key that Codex rejects.
  if ! grep -qxF 'cli_auth_credentials_store = "file"' "$codex_home/config.toml" 2>/dev/null; then
    printf 'cli_auth_credentials_store = "file"\n' >>"$codex_home/config.toml"
  fi
fi

# Write user-level instructions (global scope read by Codex CLI)
if [ -n "${KELOS_AGENTS_MD:-}" ]; then
  printf '%s' "$KELOS_AGENTS_MD" >"$codex_home/AGENTS.md"
fi

# Install each plugin as a skill directory under the configured Codex home.
installed_skill_targets=""
codex_home="${CODEX_HOME:-$HOME/.codex}"
if [ -n "${KELOS_PLUGIN_DIR:-}" ] && [ -d "${KELOS_PLUGIN_DIR}" ]; then
  for plugindir in "${KELOS_PLUGIN_DIR}"/*/; do
    [ -d "$plugindir" ] || continue
    # Copy skills into ~/.codex/skills/<plugin>:<skill>/
    if [ -d "${plugindir}skills" ]; then
      for skilldir in "${plugindir}skills"/*/; do
        [ -d "$skilldir" ] || continue
        skillname=$(basename "$skilldir")
        pluginname=$(basename "$plugindir")
        targetdir="$codex_home/skills/${pluginname}:${skillname}"
        if [ -f "${skilldir}SKILL.md" ]; then
          sourceid="${pluginname}/${skillname}"
          existing_source=""
          while IFS=$'\t' read -r seen_target seen_source; do
            [ -n "$seen_target" ] || continue
            if [ "$seen_target" = "$targetdir" ]; then
              existing_source="$seen_source"
              break
            fi
          done <<<"$installed_skill_targets"
          if [ -n "$existing_source" ] && [ "$existing_source" != "$sourceid" ]; then
            printf 'Error: Skill target conflict: %s and %s both install to %s\n' "$existing_source" "$sourceid" "$targetdir" >&2
            exit 1
          fi
          installed_skill_targets="${installed_skill_targets}${targetdir}"$'\t'"${sourceid}"$'\n'
          rm -rf "$targetdir"
          mkdir -p "$targetdir"
          cp -R "${skilldir}." "$targetdir/"
        fi
      done
    fi
  done
fi

# Write MCP server configuration to project-scoped config.
# KELOS_MCP_SERVERS contains JSON in .mcp.json format; convert to
# Codex TOML via a small Node.js helper that is available in the image.
if [ -n "${KELOS_MCP_SERVERS:-}" ]; then
  node -e '
const cfg = JSON.parse(process.env.KELOS_MCP_SERVERS);
const servers = cfg.mcpServers || {};
let toml = "";
for (const [name, s] of Object.entries(servers)) {
  toml += `[mcp_servers.${JSON.stringify(name)}]\n`;
  if (s.command) toml += `command = ${JSON.stringify(s.command)}\n`;
  if (s.args && s.args.length) toml += `args = ${JSON.stringify(s.args)}\n`;
  if (s.url) toml += `url = ${JSON.stringify(s.url)}\n`;
  if (s.headers) {
    const h = Object.entries(s.headers).map(([k,v]) => `${JSON.stringify(k)} = ${JSON.stringify(v)}`).join(", ");
    toml += `http_headers = { ${h} }\n`;
  }
  if (s.env) {
    const e = Object.entries(s.env).map(([k,v]) => `${JSON.stringify(k)} = ${JSON.stringify(v)}`).join(", ");
    toml += `env = { ${e} }\n`;
  }
  toml += "\n";
}
process.stdout.write(toml);
' >>"$codex_home/config.toml"
fi

# Run pre-agent setup command if configured. KELOS_SETUP_COMMAND is the
# JSON-encoded exec-form array from Workspace.spec.setupCommand. A non-zero
# exit aborts the task before the agent starts.
if [ -n "${KELOS_SETUP_COMMAND:-}" ]; then
  printf '\n---KELOS_SETUP_COMMAND_START---\n' >&2
  node -e '
const { spawnSync } = require("child_process");
const cmd = JSON.parse(process.env.KELOS_SETUP_COMMAND);
if (!Array.isArray(cmd) || cmd.length === 0 || cmd.some(a => typeof a !== "string")) {
  console.error("KELOS_SETUP_COMMAND must be a non-empty JSON array of strings");
  process.exit(2);
}
const r = spawnSync(cmd[0], cmd.slice(1), { stdio: "inherit" });
if (r.error) { console.error(r.error.message); process.exit(127); }
process.exit(r.status ?? 1);
'
  SETUP_EXIT_CODE=$?
  if [ "$SETUP_EXIT_CODE" -ne 0 ]; then
    printf '\n---KELOS_SETUP_COMMAND_FAILED--- exit=%s\n' "$SETUP_EXIT_CODE" >&2
    exit "$SETUP_EXIT_CODE"
  fi
  printf '\n---KELOS_SETUP_COMMAND_DONE---\n' >&2
fi

if [ "${KELOS_SESSION_SETUP_ONLY:-}" = "1" ]; then
  exit 0
fi

PROMPT="${1:?Prompt argument is required}"
ARGS=(
  "exec"
  "--dangerously-bypass-approvals-and-sandbox"
  "--json"
  "$PROMPT"
)

if [ -n "${KELOS_MODEL:-}" ]; then
  ARGS+=("--model" "$KELOS_MODEL")
fi

if [ -n "${KELOS_EFFORT:-}" ]; then
  SAFE_EFFORT=$(printf '%s' "$KELOS_EFFORT" | tr -d '"\\\n\r')
  ARGS+=("--config" "model_reasoning_effort=\"$SAFE_EFFORT\"")
fi

codex "${ARGS[@]}" | /kelos/kelos-capture
AGENT_EXIT_CODE=${PIPESTATUS[0]}

exit $AGENT_EXIT_CODE
