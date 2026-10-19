#!/bin/sh
# Renders the Kubernetes example offline and checks the security and wiring settings
# it depends on.
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

# ContainerSSH settings, read from the generated ConfigMap.
csc='select(.kind=="ConfigMap" and (.metadata.name | test("^containerssh-config"))).data["config.yaml"] | from_yaml'
# ContainerSSH appends /pubkey and /password to the auth URL (ContainerSSH v0.6.0 auth webhook docs).
authurl=$(q "$csc | .auth.publicKey.webhook.url")
case "$authurl" in
http://*/* | https://*/*) fail "auth webhook URL has no path" "got [$authurl]" ;;
http://?* | https://?*) pass "auth webhook URL has no path" ;;
*) fail "auth webhook URL has no path" "got [$authurl]" ;;
esac
cfgurl=$(q "$csc | .configserver.url")
case "$cfgurl" in
http*://*/config) pass "configserver URL ends in /config" ;;
*) fail "configserver URL ends in /config" "got [$cfgurl]" ;;
esac
assert_eq "SSH keepalive interval is set" "30s" "$(q "$csc | .ssh.clientAliveInterval")"
dep='select(.kind=="Deployment" and .metadata.name=="containerssh").spec.template.spec'
hk="$dep.volumes[] | select(.name==\"hostkey\").secret"
assert_eq "host key Secret item is host.key" "host.key host.key" "$(q "$hk | .items[0].key + \" \" + .items[0].path")"
assert_eq "hostkeys path matches the host.key mount" \
	"$(q "$dep.containers[0].volumeMounts[] | select(.name==\"hostkey\").mountPath")/host.key" \
	"$(q "$csc | .ssh.hostkeys[0]")"
# shellcheck disable=SC2016 # the README line contains a literal $keydir
assert_contains "README creates the host key Secret from host.key" \
	'create secret generic containerssh-hostkey --from-file="$keydir/host.key"' "$(cat README.md)"
assert_eq "host key file mode 0400" "256" "$(q "$hk.defaultMode")"
assert_eq "fsGroup lets user 1022 read the host key" "1022" "$(q "$dep.securityContext.fsGroup")"
for d in containerssh agentainer-auth; do
	p="select(.kind==\"Deployment\" and .metadata.name==\"$d\").spec.template.spec"
	assert_eq "$d runAsNonRoot" "true" "$(q "$p.securityContext.runAsNonRoot")"
	assert_eq "$d seccomp RuntimeDefault" "RuntimeDefault" "$(q "$p.securityContext.seccompProfile.type")"
	assert_eq "$d no privilege escalation" "false" "$(q "$p.containers[0].securityContext.allowPrivilegeEscalation")"
	assert_eq "$d drops ALL" "ALL" "$(q "$p.containers[0].securityContext.capabilities.drop | join(\" \")")"
	assert_eq "$d has resource requests and limits" "cpu memory cpu memory" \
		"$(q "$p.containers[0].resources | (.requests | keys | join(\" \")) + \" \" + (.limits | keys | join(\" \"))")"
done
svc='select(.kind=="Service" and .metadata.name=="containerssh")'
assert_eq "containerssh Service keeps the client source IP" "Local" "$(q "$svc.spec.externalTrafficPolicy")"
assert_eq "PVCs are kept on delete and scale down" "Retain Retain" \
	"$(q "$sts.spec.persistentVolumeClaimRetentionPolicy | .whenDeleted + \" \" + .whenScaled")"
assert_eq "headless Service has no ports" "None 0" \
	"$(q 'select(.kind=="Service" and .metadata.name=="agentainer").spec | .clusterIP + " " + ((.ports // []) | length | tostring)')"
assert_eq "every object has part-of agentainer" "agentainer" \
	"$(q '.metadata.labels."app.kubernetes.io/part-of"' | grep -v '^---' | sort -u | paste -sd ' ' -)"
assert_eq "selectors do not carry part-of" "" \
	"$(q '.spec.selector."app.kubernetes.io/part-of", .spec.selector.matchLabels."app.kubernetes.io/part-of", .spec.podSelector.matchLabels."app.kubernetes.io/part-of"' | grep -v -e '^---' -e '^null$' || true)"
. ./versions.env
assert_contains "containerssh digest matches versions.env" "$CONTAINERSSH_IMAGE" "$out"
assert_contains "webhook python digest matches versions.env" "$WEBHOOK_PYTHON_IMAGE" "$out"
private=$(printf '%s\n' "$out" | grep -E '(^|[^0-9.])(10\.[0-9]+\.[0-9]+\.[0-9]+|192\.168\.[0-9]+\.[0-9]+|172\.(1[6-9]|2[0-9]|3[01])\.[0-9]+\.[0-9]+)' || true)
assert_eq "no private IP addresses in manifests" "" "$private"

finish
