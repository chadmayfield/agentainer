#!/bin/bash -p
# Kelos dispatcher. Kelos starts every agent container with /kelos_entrypoint.sh
# and sets KELOS_AGENT_TYPE. This script refuses a Claude pod that carries
# credentials other than CLAUDE_CODE_OAUTH_TOKEN, then runs the Kelos entrypoint
# for the agent type.
#
# Variable and settings-key names come from the Claude Code docs:
#   https://code.claude.com/docs/en/env-vars
#   https://code.claude.com/docs/en/settings
#   https://code.claude.com/docs/en/settings-reference
# Exit codes: 78 for a refused pod, 2 for an unknown or missing agent type.
#
# Order of work: preflight (refuse BASH_ENV, ENV and exported bash functions),
# guard, proxy CA bundle, guard again, then exec. The guard also runs a last time
# in /usr/local/lib/kelos/bin/claude, right before the real claude starts, after
# the Kelos entrypoint has written its files. The Kelos entrypoints stay
# unmodified for that.
set -uo pipefail
# shellcheck disable=SC1091 # exists in the image
. /usr/local/lib/kelos/guard.sh
CAT=/usr/bin/cat MKTEMP=/usr/bin/mktemp

# When the pod gives a proxy CA file, build a bundle of the system CAs plus that
# CA. GIT_SSL_CAINFO and SSL_CERT_FILE replace the whole CA list of the tool that
# reads them, so each must point at the combined file. Readers:
#   git (libcurl)   GIT_SSL_CAINFO   combined bundle
#   gh (Go)         SSL_CERT_FILE    combined bundle (also read by OpenSSL tools)
#   Claude Code     NODE_EXTRA_CA_CERTS  the proxy CA alone; Node adds it to its own list
proxy_ca_setup() {
  local ca=${PROXY_CA_FILE:-} dir bundle
  [ -n "$ca" ] || return 0
  [ -r "$ca" ] || refuse "PROXY_CA_FILE $ca is not readable"
  "$GREP" -q 'BEGIN CERTIFICATE' "$ca" || refuse "PROXY_CA_FILE $ca holds no certificate"
  dir=$("$MKTEMP" -d "${TMPDIR:-/tmp}/kelos-ca.XXXXXX") || refuse "cannot create a directory for the CA bundle"
  bundle="$dir/ca-bundle.crt"
  "$CAT" /etc/ssl/certs/ca-certificates.crt "$ca" >"$bundle" || refuse "cannot write $bundle"
  export GIT_SSL_CAINFO="$bundle" SSL_CERT_FILE="$bundle" NODE_EXTRA_CA_CERTS="$ca"
}

kelos_preflight

case "${KELOS_AGENT_TYPE:-}" in
claude-code)
  claude_guard
  proxy_ca_setup
  claude_guard
  # The Claude entrypoint writes KELOS_AGENTS_MD and ~/.claude.json after this
  # point and then runs "claude". The wrapper directory comes first on PATH, so
  # that call runs the guard once more and then the real binary.
  export PATH="/usr/local/lib/kelos/bin:$PATH"
  exec /kelos_entrypoint_claude.sh "$@"
  ;;
codex)
  codex_guard
  proxy_ca_setup
  exec /kelos_entrypoint_codex.sh "$@"
  ;;
*)
  printf 'kelos_entrypoint: KELOS_AGENT_TYPE must be claude-code or codex, got "%s"\n' "${KELOS_AGENT_TYPE:-}" >&2
  exit 2
  ;;
esac
