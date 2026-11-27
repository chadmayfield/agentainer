# Say when sudo can gain root. The image has passwordless sudo, and only the
# runtime's no-new-privileges setting (Kubernetes: allowPrivilegeEscalation: false) turns
# it off. This is a warning, so it prints for one-shot commands too (AGENTAINER_QUIET=1).
# The kernel reports the flag in /proc/<pid>/status; children inherit it.
nnp=$(sed -n 's/^NoNewPrivs:[[:space:]]*//p' /proc/self/status 2>/dev/null || true)
if [ "$nnp" = 0 ] && sudo -n true </dev/null >/dev/null 2>&1; then
	warn "sudo works in this container, so agents can become root; start it with --security-opt no-new-privileges=true (agentainer up without --sudo) to turn sudo off"
fi
