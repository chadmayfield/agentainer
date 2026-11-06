#!/bin/bash -p
# Installed as /usr/local/lib/kelos/mcp-headers. Claude runs it as the
# headersHelper of the gateway MCP server (claude-wrapper.sh writes that config)
# and sends the JSON object it prints as HTTP headers. Claude removes variables
# with names like TOKEN or KEY from a helper's environment, so the token is read
# from the mounted file. It is checked against the guard's token rule and never
# appears on a command line: jq reads the file itself.
set -uo pipefail
# shellcheck disable=SC1091 # exists in the image
. /usr/local/lib/kelos/guard.sh
# shellcheck disable=SC2154 # mcp_dir and mcp_error are set in guard.sh
token_file=$mcp_dir/token
if ! mcp_token_valid "$token_file"; then
  # shellcheck disable=SC2154 # set by mcp_token_valid
  printf 'mcp-headers: %s\n' "$mcp_error" >&2
  exit 1
fi
# shellcheck disable=SC2016 # $t is a jq variable
exec "$JQ" -cn --rawfile t "$token_file" '{Authorization: ("Bearer " + ($t | rtrimstr("\n")))}'
