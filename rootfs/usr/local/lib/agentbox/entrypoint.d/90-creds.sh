# Step 9: list credential variable names, never values (spec 6.2). Quiet for one-shot
# commands (AGENTBOX_QUIET=1, set by the entrypoint); warnings always print.
is_set() { eval "[ -n \"\${$1+x}\" ]"; }
is_blank() { eval "[ -z \"\$(printf '%s' \"\${$1}\" | tr -d '[:space:]')\" ]"; }
found=""
empty=""
for v in ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN CLAUDE_CODE_OAUTH_TOKEN OPENAI_API_KEY CODEX_API_KEY \
	GEMINI_API_KEY GOOGLE_API_KEY GOOGLE_GENERATIVE_AI_API_KEY OPENROUTER_API_KEY \
	GH_TOKEN GITHUB_TOKEN GH_ENTERPRISE_TOKEN; do
	is_set "$v" || continue
	if is_blank "$v"; then empty="$empty $v"; else found="$found $v"; fi
done
for v in GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL; do
	if is_set "$v" && is_blank "$v"; then empty="$empty $v"; fi
done
if [ "${AGENTBOX_QUIET:-0}" != 1 ]; then
	if [ -n "$found" ]; then
		log "credential variables set:$found"
	else
		log "no credential variables set"
	fi
fi
if [ -n "$empty" ]; then
	warn "set but empty (comment them out in your env file):$empty"
fi
