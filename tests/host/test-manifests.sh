#!/bin/sh
# Renders the Kubernetes example offline and checks the settings the spec requires.
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/../lib.sh"
cd "$(dirname "$0")/../.." || exit 2
if ! out=$(kubectl kustomize deploy/kubernetes); then
	fail "kustomize renders"
	finish
	exit 1
fi
pass "kustomize renders"
q() { printf '%s\n' "$out" | "$RUNTIME" run --rm -i --entrypoint yq "$IMAGE" "$1"; }
sts='select(.kind=="StatefulSet")'
assert_eq "runAsNonRoot" "true" "$(q "$sts.spec.template.spec.securityContext.runAsNonRoot")"
assert_eq "fsGroupChangePolicy" "OnRootMismatch" "$(q "$sts.spec.template.spec.securityContext.fsGroupChangePolicy")"
assert_eq "ping sysctl" "net.ipv4.ping_group_range" "$(q "$sts.spec.template.spec.securityContext.sysctls[0].name")"
assert_eq "no service account token" "false" "$(q "$sts.spec.template.spec.automountServiceAccountToken")"
assert_eq "no privilege escalation" "false" "$(q "$sts.spec.template.spec.containers[0].securityContext.allowPrivilegeEscalation")"
assert_eq "drops ALL" "ALL" "$(q "$sts.spec.template.spec.containers[0].securityContext.capabilities.drop[0]")"
assert_eq "seccomp RuntimeDefault" "RuntimeDefault" "$(q "$sts.spec.template.spec.securityContext.seccompProfile.type")"
assert_eq "SSH targetPort 2222" "2222" "$(q 'select(.kind=="Service" and .metadata.name=="containerssh").spec.ports[0].targetPort')"
assert_eq "restricted namespace" "restricted" "$(q 'select(.kind=="Namespace" and .metadata.name=="agentainer").metadata.labels."pod-security.kubernetes.io/enforce"')"
assert_eq "RBAC verbs are only create and get" "create get" "$(q 'select(.kind=="Role") | .rules[].verbs[]' | grep -v '^---' | sort -u | paste -sd ' ' -)"
cfg=$(q 'select(.kind=="Deployment" and .metadata.name=="containerssh").spec.template.spec.volumes[] | select(.name=="config").configMap.name')
case "$cfg" in
containerssh-config-?*) pass "containerssh config name carries a content hash, so edits roll out" ;;
*) fail "containerssh config name carries a content hash, so edits roll out" "got [$cfg]" ;;
esac
assert_eq "webhook URLs do not assume cluster.local" "" "$(printf '%s\n' "$out" | grep 'cluster\.local' || true)"
assert_eq "agentainer image is set through kustomize images" "ghcr.io/chadmayfield/agentainer" \
	"$("$RUNTIME" run --rm -i --entrypoint yq "$IMAGE" '.images[0].name' <deploy/kubernetes/agentainer/kustomization.yaml)"
assert_eq "RBAC is limited to the agentainer-0 pod" "agentainer-0 agentainer-0" \
	"$(q 'select(.kind=="Role") | .rules[].resourceNames[]' | grep -v '^---' | paste -sd ' ' -)"
wh='select(.kind=="NetworkPolicy" and .metadata.name=="agentainer-auth-ingress")'
assert_eq "webhook ingress policy selects the webhook" "agentainer-auth" "$(q "$wh.spec.podSelector.matchLabels.app")"
assert_eq "webhook ingress admits only ContainerSSH" "containerssh" "$(q "$wh.spec.ingress[0].from[0].podSelector.matchLabels.app")"
assert_eq "webhook ingress port" "8080" "$(q "$wh.spec.ingress[0].ports[0].port")"
. ./versions.env
assert_contains "containerssh digest matches versions.env" "$CONTAINERSSH_IMAGE" "$out"
assert_contains "webhook python digest matches versions.env" "$WEBHOOK_PYTHON_IMAGE" "$out"
private=$(printf '%s\n' "$out" | grep -E '(^|[^0-9.])(10\.[0-9]+\.[0-9]+\.[0-9]+|192\.168\.[0-9]+\.[0-9]+|172\.(1[6-9]|2[0-9]|3[01])\.[0-9]+\.[0-9]+)' || true)
assert_eq "no private IP addresses in manifests" "" "$private"

finish
