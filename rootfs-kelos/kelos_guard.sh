#!/bin/bash -p
# Guard functions shared by the Kelos dispatcher and the claude wrapper. Source
# this file; do not run it. See kelos_entrypoint.sh for the reasoning.
# Variables the claude wrapper passes to the real claude; everything else is
# dropped by env -i. Each entry says why. The Kelos controller's list of
# variables comes from internal/controller/job_builder.go (v0.62.0); the Claude
# Code names from https://code.claude.com/docs/en/env-vars and
# https://code.claude.com/docs/en/network-config.
# shellcheck disable=SC2034 # used by claude-wrapper.sh and the tests
claude_env_allowlist=(
  HOME USER LOGNAME SHELL TMPDIR # process identity and scratch space for claude and the tools it starts
  LANG LC_ALL LC_CTYPE TZ TERM   # locale, time zone and terminal type
  CLAUDE_CODE_OAUTH_TOKEN        # the only credential a Claude pod gets
  DISABLE_UPDATES CLAUDE_CODE_NONBLOCKING_STDOUT CLAUDE_CODE_TMUX_TRUECOLOR # image ENV: update lock and output behavior
  HTTP_PROXY HTTPS_PROXY NO_PROXY http_proxy https_proxy no_proxy # egress proxy; claude reads both spellings (network-config)
  GIT_SSL_CAINFO SSL_CERT_FILE NODE_EXTRA_CA_CERTS # CA bundle for git, gh and claude, set by the dispatcher
  GITHUB_TOKEN GH_TOKEN GH_ENTERPRISE_TOKEN GH_HOST GH_CONFIG_DIR # set by Kelos when the Workspace has a secretRef (job_builder.go)
  KELOS_GITHUB_TOKEN_FILE        # read by the gh wrapper at /usr/local/bin/gh
  KELOS_BRANCH KELOS_BASE_BRANCH KELOS_UPSTREAM_REPO # Task context the agent's shell and prompt can use
  GOPATH GOBIN GOTOOLCHAIN RUSTUP_HOME CARGO_HOME CARGO_INSTALL_ROOT # image ENV for the agent's build tools
  NPM_CONFIG_PREFIX UV_TOOL_DIR UV_TOOL_BIN_DIR PIPX_HOME PIPX_BIN_DIR PYTHONUSERBASE # image ENV for installed tools
)

# Commands the guard runs, by absolute path so that PATH cannot replace them.
JQ=/usr/bin/jq GIT=/usr/bin/git GREP=/usr/bin/grep TR=/usr/bin/tr

refuse() {
  printf 'kelos_entrypoint: refusing to start: %s\n' "$1" >&2
  exit 78
}

# Run first. Exported bash functions reach a child bash as BASH_FUNC_<name>%%
# variables and replace commands such as jq. Scripts here start with
# "#!/bin/bash -p", and bash in privileged mode does not import them, but the
# variables stay in the environment for the Kelos entrypoints (plain bash), so any
# of them is refused. /proc/$$/environ holds the environment this process started
# with.
kelos_preflight() {
  local loader
  for loader in BASH_ENV ENV; do
    if [ -n "${!loader+x}" ]; then
      refuse "environment variable $loader is set"
    fi
  done
  unset BASH_ENV ENV
  # HOME must be the image user's home. Pointed into the checkout, a repo file
  # such as .claude.json with primaryApiKey would replace the OAuth token.
  if [ -n "${HOME+x}" ] && [ "$HOME" != /home/kelos ]; then
    refuse "HOME is $HOME, not /home/kelos"
  fi
  export HOME=/home/kelos
  # Dynamic-loader and Node option variables change what every child runs.
  for loader in LD_PRELOAD LD_LIBRARY_PATH LD_AUDIT NODE_OPTIONS; do
    if [ -n "${!loader+x}" ]; then
      refuse "environment variable $loader is set"
    fi
  done
  # PATH must be the image's own PATH, with or without the wrapper directory in
  # front, and may only have more entries after it. The image PATH is set by ENV
  # in Containerfile.kelos; keep the two in step.
  local expected=/home/kelos/.local/bin:/usr/local/go/bin:/opt/cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
  local current=${PATH#/usr/local/lib/kelos/bin:}
  case "$current" in
  "$expected" | "$expected":*) ;;
  *) refuse "PATH does not start with the image PATH ($expected)" ;;
  esac
  # No empty entry (it means the working directory, the repo checkout), and no
  # relative entry or ".." component anywhere in PATH.
  case ":$PATH:" in
  *::*) refuse "PATH has an empty entry" ;;
  esac
  local entry
  local -a entries
  IFS=: read -ra entries <<<"$PATH"
  for entry in "${entries[@]}"; do
    case "$entry" in
    /*) ;;
    *) refuse "PATH entry \"$entry\" is not an absolute path" ;;
    esac
    case "/$entry/" in
    */../* | */./*) refuse "PATH entry \"$entry\" has a . or .. component" ;;
    esac
  done
  # KELOS_MCP_SERVERS makes the Kelos entrypoint start arbitrary stdio commands
  # after every guard. This image does not use MCP servers, so only an empty value
  # passes.
  if [ -n "${KELOS_MCP_SERVERS:-}" ]; then
    refuse "KELOS_MCP_SERVERS is set; this image does not support MCP servers"
  fi
  if "$TR" '\0' '\n' <"/proc/$$/environ" | "$GREP" -aq '^BASH_FUNC_'; then
    refuse "an exported bash function (BASH_FUNC_*) is in the environment"
  fi
}

# API keys, bearer tokens, cloud-provider selectors and credentials, gateway and
# federation variables. A pod that sets any of these, even to an empty value,
# is refused. Names compare case-insensitively.
claude_forbidden_env=(
  ANTHROPIC_API_KEY
  ANTHROPIC_AUTH_TOKEN
  ANTHROPIC_BASE_URL
  ANTHROPIC_PROFILE
  ANTHROPIC_FEDERATION_RULE_ID
  ANTHROPIC_ORGANIZATION_ID
  ANTHROPIC_WORKSPACE_ID
  CLAUDE_CODE_USE_BEDROCK
  CLAUDE_CODE_USE_VERTEX
  CLAUDE_CODE_USE_FOUNDRY
  CLAUDE_CODE_USE_MANTLE
  CLAUDE_CODE_USE_ANTHROPIC_AWS
  AWS_BEARER_TOKEN_BEDROCK
  ANTHROPIC_FOUNDRY_API_KEY
  ANTHROPIC_FOUNDRY_AUTH_TOKEN
  ANTHROPIC_AWS_API_KEY
)

# Settings keys that run a credential command.
claude_forbidden_keys=(apiKeyHelper awsAuthRefresh awsCredentialExport gcpAuthRefresh)

# KELOS_SETUP_COMMAND comes from Workspace.spec.setupCommand (job_builder.go in
# Kelos v0.62.0; PodOverrides.Env cannot set it). The Claude entrypoint runs it
# after this guard, and it could write a settings file. This image does not
# support a setup command on Claude pods, so a pod that has one is refused.
claude_guard() {
  local name file dir root key lower_names out
  for name in "${claude_forbidden_env[@]}"; do
    if [ -n "${!name+x}" ]; then
      refuse "environment variable $name is set"
    fi
  done
  # Lowercase spellings of the same names.
  while IFS= read -r name; do
    for key in "${claude_forbidden_env[@]}"; do
      if [ "${name,,}" = "${key,,}" ]; then
        refuse "environment variable $name is set"
      fi
    done
  done < <(compgen -e)
  if [ -n "${KELOS_SETUP_COMMAND+x}" ]; then
    refuse "KELOS_SETUP_COMMAND is set, and it runs after the guard"
  fi
  # CLAUDE_CONFIG_DIR moves where claude reads settings and .claude.json. This
  # image keeps them in the home directory, so a pod that sets it is refused.
  if [ -n "${CLAUDE_CONFIG_DIR+x}" ]; then
    refuse "CLAUDE_CONFIG_DIR is set"
  fi

  # Every settings file the CLI reads on Linux: user (honouring CLAUDE_CONFIG_DIR),
  # project and project-local files for the working directory and the git root,
  # and the managed files. Each file is parsed as JSON so that escapes such as
  # \u0061piKeyHelper are decoded. A file that is not valid JSON is refused, and so
  # is any file with a forbidden key at any depth, which includes an "env" block.
  local files=(
    "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json"
    "$HOME/.claude/settings.json"
    /etc/claude-code/managed-settings.json
  )
  files+=(/etc/claude-code/managed-settings.d/*.json)
  root=$("$GIT" rev-parse --show-toplevel 2>/dev/null || true)
  for dir in "$PWD" "$root"; do
    [ -n "$dir" ] || continue
    files+=("$dir/.claude/settings.json" "$dir/.claude/settings.local.json")
  done

  lower_names=$(printf '%s\n' "${claude_forbidden_keys[@]}" "${claude_forbidden_env[@]}" | "$TR" '[:upper:]' '[:lower:]' | "$JQ" -R . | "$JQ" -sc .)
  for file in "${files[@]}"; do
    # A symlink, or a symlinked parent directory, is refused even when it
    # dangles: the entrypoint writes KELOS_AGENTS_MD into the Claude config
    # directory, and a link would carry that text into a settings file.
    if [ -L "$file" ] || [ -L "${file%/*}" ]; then
      refuse "$file or its directory is a symlink"
    fi
    if [ -e "$file" ] && [ ! -f "$file" ]; then
      refuse "$file is not a regular file"
    fi
    [ -f "$file" ] || continue
    # shellcheck disable=SC2016 # $f is a jq variable
    if ! out=$("$JQ" -r --argjson f "$lower_names" 'first(.. | objects | keys[] | select(ascii_downcase | IN($f[])))' "$file" 2>/dev/null); then
      refuse "$file is not valid JSON"
    fi
    if [ -n "$out" ]; then
      refuse "$file contains $out"
    fi
  done
}

# Codex credentials that outrank auth.json, or redirect it. In codex 0.163.0
# (openai/codex rust-v0.163.0, login/src/auth/manager.rs) CODEX_API_KEY and
# CODEX_ACCESS_TOKEN are checked before auth.json, and
# CODEX_REFRESH_TOKEN_URL_OVERRIDE sends the refresh token elsewhere. The
# OpenAI key is refused too, so a Codex pod only ever uses the ChatGPT login.
# CODEX_HOME may only be the default, so auth.json stays on the codex-auth volume.
codex_guard() {
  local name key
  while IFS= read -r name; do
    for key in CODEX_API_KEY OPENAI_API_KEY CODEX_ACCESS_TOKEN CODEX_REFRESH_TOKEN_URL_OVERRIDE; do
      if [ "${name^^}" = "$key" ]; then
        refuse "environment variable $name is set"
      fi
    done
  done < <(compgen -e)
  if [ -n "${CODEX_HOME+x}" ] && [ "$CODEX_HOME" != /home/kelos/.codex ]; then
    refuse "CODEX_HOME is $CODEX_HOME, not /home/kelos/.codex"
  fi
}
