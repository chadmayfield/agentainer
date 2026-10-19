# shellcheck shell=sh
# Sourced by the entrypoint's tools step and by agentainer-tools.
# Creates a tools root. npm needs <prefix>/lib even before the first global install;
# without it npx fails with "ENOENT: lstat .../npm/lib", and so does every MCP server
# started with npx.
tools_mkdirs() {
	mkdir -p "$1/bin" "$1/npm/bin" "$1/npm/lib"
}
