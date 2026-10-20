# Step 8: sync changed MCP input. The command holds the shared-home lock while it
# compares the input hash, updates every agent and saves the manifest and hash.
agentainer-mcp sync --if-changed
