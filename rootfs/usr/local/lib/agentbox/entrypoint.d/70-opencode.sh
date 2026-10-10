# Step 7: make OpenCode use a private server per command, once (spec 3.4). The
# setting is stored in ~/.config/opencode/service.json.
marker="$HOME/.agentbox/.opencode-service-disabled"
[ -f "$marker" ] && return 0
opencode service set disabled true >/dev/null && touch "$marker"
