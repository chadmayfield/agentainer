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
assert_eq "startup probe permits three minutes" "5 36" \
	"$(q "$sts.spec.template.spec.containers[0].startupProbe | (.periodSeconds | tostring) + \" \" + (.failureThreshold | tostring)")"
assert_eq "readiness probe executes local checks" "sh" \
	"$(q "$sts.spec.template.spec.containers[0].readinessProbe.exec.command[0]")"
assert_eq "runAsNonRoot" "true" "$(q "$sts.spec.template.spec.securityContext.runAsNonRoot")"
assert_eq "fsGroupChangePolicy" "OnRootMismatch" "$(q "$sts.spec.template.spec.securityContext.fsGroupChangePolicy")"
assert_eq "ping sysctl" "net.ipv4.ping_group_range" "$(q "$sts.spec.template.spec.securityContext.sysctls[0].name")"
assert_eq "no service account token" "false" "$(q "$sts.spec.template.spec.automountServiceAccountToken")"
assert_eq "no privilege escalation" "false" "$(q "$sts.spec.template.spec.containers[0].securityContext.allowPrivilegeEscalation")"
assert_eq "drops ALL" "ALL" "$(q "$sts.spec.template.spec.containers[0].securityContext.capabilities.drop[0]")"
assert_eq "seccomp RuntimeDefault" "RuntimeDefault" "$(q "$sts.spec.template.spec.securityContext.seccompProfile.type")"
assert_eq "SSH targetPort 2222" "2222" "$(q 'select(.kind=="Service" and .metadata.name=="containerssh").spec.ports[0].targetPort')"
assert_eq "restricted namespace" "restricted" "$(q 'select(.kind=="Namespace" and .metadata.name=="agentainer").metadata.labels."pod-security.kubernetes.io/enforce"')"
# ContainerSSH v0.6.0 reads the pod (Pods().Get) and runs exec with a POST SPDY request,
# which RBAC authorizes as create on pods/exec.
assert_eq "RBAC allows get on pods and create on pods/exec, nothing else" "pods=get pods/exec=create" \
	"$(q 'select(.kind=="Role") | .rules[] | (.resources | join(",")) + "=" + (.verbs | join(","))' | grep -v '^---' | paste -sd ' ' -)"
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
# shellcheck disable=SC2016 # the docs line contains a literal $keydir
assert_contains "docs/kubernetes.md creates the host key Secret from host.key" \
	'create secret generic containerssh-hostkey --from-file="$keydir/host.key"' "$(cat docs/kubernetes.md)"
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
assert_eq "seed ConfigMap volume is optional" "agentainer-seed true" \
	"$(q "$sts.spec.template.spec.volumes[] | select(.name==\"seed\").configMap | .name + \" \" + (.optional | tostring)")"
assert_eq "seed volume is mounted read-only at /etc/agentainer/seed" "/etc/agentainer/seed true" \
	"$(q "$sts.spec.template.spec.containers[0].volumeMounts[] | select(.name==\"seed\") | .mountPath + \" \" + (.readOnly | tostring)")"
assert_contains "docs/kubernetes.md shows how to create the seed ConfigMap" \
	"kubectl -n agentainer create configmap agentainer-seed" "$(cat docs/kubernetes.md)"
assert_eq "PVCs are kept on delete and scale down" "Retain Retain" \
	"$(q "$sts.spec.persistentVolumeClaimRetentionPolicy | .whenDeleted + \" \" + .whenScaled")"
assert_eq "agentainer container sets TZ and LANG" "UTC C.UTF-8" \
	"$(q "$sts.spec.template.spec.containers[0].env | (map(select(.name==\"TZ\"))[0].value) + \" \" + (map(select(.name==\"LANG\"))[0].value)")"
# Rendered output drops YAML comments, so check the source file.
assert_eq "statefulset comment shows a changed time zone" "0" \
	"$(grep -q 'America/Denver' deploy/kubernetes/agentainer/statefulset.yaml >/dev/null 2>&1 && echo 0 || echo 1)"
assert_eq "headless Service has no ports" "None 0" \
	"$(q 'select(.kind=="Service" and .metadata.name=="agentainer").spec | .clusterIP + " " + ((.ports // []) | length | tostring)')"
assert_eq "every object has part-of agentainer" "agentainer" \
	"$(q '.metadata.labels."app.kubernetes.io/part-of"' | grep -v '^---' | sort -u | paste -sd ' ' -)"
# One line per object: how many selectors it has and how many of them carry part-of.
# The marker "selectors=1" proves yq ran and the paths reach real selectors.
assert_absent "selectors do not carry part-of" \
	"$(q '"selectors=" + ([.spec.selector, .spec.podSelector] | map(select(. != null)) | length | tostring) + " part-of=" + ([.spec.selector."app.kubernetes.io/part-of", .spec.selector.matchLabels."app.kubernetes.io/part-of", .spec.podSelector.matchLabels."app.kubernetes.io/part-of"] | map(select(. != null)) | length | tostring)')" \
	"selectors=1 " part-of=1 part-of=2 part-of=3
. ./versions.env
assert_contains "containerssh digest matches versions.env" "$CONTAINERSSH_IMAGE" "$out"
assert_contains "webhook python digest matches versions.env" "$WEBHOOK_PYTHON_IMAGE" "$out"
private=$(printf '%s\n' "$out" | grep -E '(^|[^0-9.])(10\.[0-9]+\.[0-9]+\.[0-9]+|192\.168\.[0-9]+\.[0-9]+|172\.(1[6-9]|2[0-9]|3[01])\.[0-9]+\.[0-9]+)' || true)
assert_eq "no private IP addresses in manifests" "" "$private"

# The agentainer pod: shared memory, the transfer volume and the FileBrowser Quantum sidecar.
pod="$sts.spec.template.spec"
assert_eq "/dev/shm is memory-backed with a 1Gi limit" "Memory 1Gi" \
	"$(q "$pod.volumes[] | select(.name==\"dshm\").emptyDir | .medium + \" \" + .sizeLimit")"
assert_eq "agent container mounts dshm at /dev/shm" "/dev/shm" \
	"$(q "$pod.containers[0].volumeMounts[] | select(.name==\"dshm\").mountPath")"
assert_eq "agentainer-transfer PVC is 5Gi ReadWriteOnce with the default storage class" \
	"agentainer 5Gi ReadWriteOnce false" \
	"$(q 'select(.kind=="PersistentVolumeClaim" and .metadata.name=="agentainer-transfer") | .metadata.namespace + " " + .spec.resources.requests.storage + " " + (.spec.accessModes | join(",")) + " " + (.spec | has("storageClassName") | tostring)')"
assert_eq "transfer volume uses the agentainer-transfer PVC" "agentainer-transfer" \
	"$(q "$pod.volumes[] | select(.name==\"transfer\").persistentVolumeClaim.claimName")"
assert_eq "volumeClaimTemplates are only home and workspace" "home=20Gi workspace=50Gi" \
	"$(q "$sts.spec.volumeClaimTemplates | map(.metadata.name + \"=\" + .spec.resources.requests.storage) | join(\" \")")"
assert_eq "agent container mounts transfer/files at /home/agent/transfer" "/home/agent/transfer files" \
	"$(q "$pod.containers[0].volumeMounts[] | select(.name==\"transfer\") | .mountPath + \" \" + .subPath")"
assert_eq "agent container stays first, filebrowser is second" "agentainer filebrowser" \
	"$(q "$pod.containers | map(.name) | join(\" \")")"
fb="$pod.containers[1]"
assert_contains "FILEBROWSER_IMAGE in versions.env is pinned by digest" "docker.io/gtstef/filebrowser:2.0-stable-slim@sha256:" "$FILEBROWSER_IMAGE"
assert_eq "filebrowser image matches FILEBROWSER_IMAGE in versions.env" "$FILEBROWSER_IMAGE" "$(q "$fb.image")"
assert_eq "filebrowser has the agent container's securityContext" "true" \
	"$(q "$pod | (.containers[1].securityContext | to_json) == (.containers[0].securityContext | to_json)")"
assert_eq "filebrowser drops ALL and blocks privilege escalation" "false ALL" \
	"$(q "$fb.securityContext | (.allowPrivilegeEscalation | tostring) + \" \" + (.capabilities.drop | join(\" \"))")"
assert_eq "filebrowser config and database paths" \
	"/etc/filebrowser/config.yaml /home/filebrowser/data/database.sqlite" \
	"$(q "$fb.env | (map(select(.name==\"FILEBROWSER_CONFIG\"))[0].value) + \" \" + (map(select(.name==\"FILEBROWSER_DATABASE_PATH\"))[0].value)")"
assert_eq "filebrowser mounts" \
	"filebrowser-config:/etc/filebrowser::true transfer:/home/filebrowser/data:filebrowser:false transfer:/srv/transfer:files:false" \
	"$(q "$fb.volumeMounts | map(.name + \":\" + .mountPath + \":\" + (.subPath // \"\") + \":\" + ((.readOnly // false) | tostring)) | join(\" \")")"
assert_eq "filebrowser-config volume is the agentainer-filebrowser ConfigMap" "agentainer-filebrowser" \
	"$(q "$pod.volumes[] | select(.name==\"filebrowser-config\").configMap.name")"
for probe in startupProbe livenessProbe; do
	assert_eq "filebrowser $probe runs curl against 127.0.0.1:8080/health" \
		"curl -fsS -o /dev/null http://127.0.0.1:8080/health" \
		"$(q "$fb.$probe.exec.command | join(\" \")")"
done
assert_eq "filebrowser resources" "50m 64Mi 500m 256Mi" \
	"$(q "$fb.resources | .requests.cpu + \" \" + .requests.memory + \" \" + .limits.cpu + \" \" + .limits.memory")"
fbcfg='select(.kind=="ConfigMap" and .metadata.name=="agentainer-filebrowser").data["config.yaml"]'
assert_eq "filebrowser listens on 127.0.0.1:8080" "127.0.0.1:8080" \
	"$(q "$fbcfg | from_yaml | .http.listen + \":\" + (.http.port | tostring)")"
assert_eq "filebrowser WebDAV is disabled" "true" "$(q "$fbcfg | from_yaml | .http.disableWebDAV")"
assert_eq "filebrowser cacheDir is under the data mount" "/home/filebrowser/data/cache" \
	"$(q "$fbcfg | from_yaml | .server.cacheDir")"
assert_eq "filebrowser has one source, /srv/transfer" "/srv/transfer" \
	"$(q "$fbcfg | from_yaml | .server.sources | map(.path) | join(\" \")")"
assert_eq "filebrowser password login is enabled" "true" "$(q "$fbcfg | from_yaml | .auth.methods.password.enabled")"
assert_absent "filebrowser config has no noauth and no admin password" "$(q "$fbcfg")" \
	"disableWebDAV" noauth adminPassword
assert_absent "no Service in the agentainer namespace exposes port 8080" \
	"$(q 'select(.kind=="Service" and .metadata.namespace=="agentainer") | "svc=" + .metadata.name + " ports=" + ((.spec.ports // []) | map((.port | tostring) + ":" + ((.targetPort // .port) | tostring)) | join(","))')" \
	"svc=agentainer " 8080
assert_absent "the optional agentainer policies are not rendered by default" \
	"$(q 'select(.kind=="NetworkPolicy") | .metadata.namespace + "/" + .metadata.name')" \
	"agentainer-auth-ingress" agentainer/agentainer-egress agentainer/agentainer-ingress
kz=deploy/kubernetes/agentainer/kustomization.yaml
assert_contains "kustomization lists the egress policy as optional" "# - networkpolicy.yaml" "$(cat "$kz")"
assert_contains "kustomization lists the ingress policy as optional" "# - ingress-policy.yaml" "$(cat "$kz")"
# The optional policies are not rendered, so read their source files.
fq() { "$RUNTIME" run --rm -i --entrypoint yq "$IMAGE" "$1" <"$2"; }
np=deploy/kubernetes/agentainer/networkpolicy.yaml
assert_eq "egress policy still allows DNS to any destination" "UDP/53 TCP/53 to=false" \
	"$(fq '.spec.egress[0] | (.ports | map(.protocol + "/" + (.port | tostring)) | join(" ")) + " to=" + (has("to") | tostring)' "$np")"
assert_eq "egress 443 rules exclude private ranges" \
	"0.0.0.0/0 except 10.0.0.0/8,172.16.0.0/12,192.168.0.0/16|::/0 except fc00::/7" \
	"$(fq '[.spec.egress[] | select(.ports[0].port == 443) | .to[].ipBlock | .cidr + " except " + (.except | join(","))] | join("|")' "$np")"
assert_eq "egress rules with destinations allow TCP 443 only" "TCP/443 TCP/443" \
	"$(fq '[.spec.egress[] | select(has("to")) | .ports[] | .protocol + "/" + (.port | tostring)] | join(" ")' "$np")"
assert_contains "egress policy shows a narrow allow rule example" "203.0.113.0/24" "$(cat "$np")"
ip=deploy/kubernetes/agentainer/ingress-policy.yaml
assert_eq "ingress policy denies all ingress to the agentainer pod" "agentainer Ingress 0" \
	"$(fq '.metadata.namespace + " " + (.spec.policyTypes | join(",")) + " " + ((.spec.ingress // []) | length | tostring)' "$ip")"
assert_eq "ingress policy selects the agentainer pod" "agentainer" "$(fq '.spec.podSelector.matchLabels.app' "$ip")"

finish
