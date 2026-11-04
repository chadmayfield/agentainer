# Kubernetes with ContainerSSH

[`deploy/kubernetes/`](../deploy/kubernetes/) has an example you apply with `kubectl apply -k`. You reach the agent pod over SSH through [ContainerSSH](https://containerssh.io/v0.6/) v0.6, and each login lands in the same tmux session.

- Namespace `agentainer`: a StatefulSet with one pod, `agentainer-0`, and two volumes, `home` (20 Gi) and `workspace` (50 Gi). It meets the [Restricted Pod Security Standard](https://kubernetes.io/docs/concepts/security/pod-security-standards/), mounts no service account token, and keeps sudo off. The pod also runs [FileBrowser Quantum](#file-transfer-and-filebrowser) as a second container and mounts a 5 Gi `agentainer-transfer` volume.
- Namespace `containerssh`: the ContainerSSH server in [persistent mode](https://containerssh.io/v0.6/reference/kubernetes/#persistent-mode), and a small Python webhook that checks SSH public keys and tells ContainerSSH which pod to use. A NetworkPolicy lets only ContainerSSH reach the webhook, if your CNI enforces NetworkPolicy.
- The ContainerSSH image on Docker Hub is amd64 only, so its Deployment runs on amd64 nodes. The agentainer pod runs on either architecture.

Verified on 2026-11-04 on a Kubernetes v1.36.2 cluster with flannel and kube-network-policies, which enforces NetworkPolicy: SSH logins, SFTP and port forwarding closed by default and opened at runtime, FileBrowser, the egress policy, Playwright in the Restricted pod, and an upgrade from the previous example. The results are quoted in the sections below. The test used test-only namespaces and its own credentials.

## Contents

- [Install](#install)
- [Logging in](#logging-in)
- [SFTP and port forwarding](#sftp-and-port-forwarding)
- [File transfer and FileBrowser](#file-transfer-and-filebrowser)
- [Shared memory](#shared-memory)
- [Limits](#limits)
- [SSH port access](#ssh-port-access)
- [Seeding a new home](#seeding-a-new-home)
- [Network policy](#network-policy)
- [Your own config server](#your-own-config-server)
- [Upgrading and removing](#upgrading-and-removing)
- [Troubleshooting](#troubleshooting)
- [More than one user](#more-than-one-user)

## Install

Before you apply, set `loadBalancerSourceRanges` in [`containerssh/service.yaml`](../deploy/kubernetes/containerssh/service.yaml) to your client range, block node ports with a firewall (see [SSH port access](#ssh-port-access)), and pin the image in [`agentainer/kustomization.yaml`](../deploy/kubernetes/agentainer/kustomization.yaml) (`images`, `newTag`). The example follows `latest`, which does not exist before the first stable release. Until then, set a published prerelease such as `0.1.0-dev.20261024.1` before applying these manifests ([release policy](versions.md#releases)).

```sh
kubectl apply -f deploy/kubernetes/agentainer/namespace.yaml \
  -f deploy/kubernetes/containerssh/namespace.yaml
kubectl -n agentainer create secret generic agentainer-credentials \
  --from-env-file="$HOME/.config/agentainer/env"
keydir=$(mktemp -d)   # keep the private host key out of the repo
openssl genrsa -out "$keydir/host.key" 4096
kubectl -n containerssh create secret generic containerssh-hostkey --from-file="$keydir/host.key"
rm -r "$keydir"
kubectl -n containerssh create secret generic agentainer-authorized-keys \
  --from-file=authorized_keys="$HOME/.ssh/id_ed25519.pub"
kubectl apply -k deploy/kubernetes
ssh dev@<containerssh service address>
```

- The namespace files carry the `pod-security.kubernetes.io/enforce: restricted` label, so the namespaces enforce the Restricted profile before any pod starts.
- ContainerSSH wants a host key from `openssl genrsa`, not `ssh-keygen` ([installation](https://containerssh.io/v0.6/reference/installation/)). Keep the file name `host.key`: the Deployment mounts only that item of the Secret, and the pod does not start without it.
- The SSH username is `AGENTAINER_USER` in [`auth-webhook/deployment.yaml`](../deploy/kubernetes/auth-webhook/deployment.yaml) (`dev` by default).

## Logging in

- The webhook accepts plain `authorized_keys` lines with these key types: `ssh-ed25519`, `ssh-rsa`, `ecdsa-sha2-nistp256`, `ecdsa-sha2-nistp384`, `ecdsa-sha2-nistp521`, `sk-ssh-ed25519@openssh.com` and `sk-ecdsa-sha2-nistp256@openssh.com`.
- It refuses lines with options such as `from=` or `command=`, because it cannot enforce them, and certificate lines (`*-cert-v01@openssh.com`), which `sshd` trusts only through `cert-authority`. Password logins always fail.
- Each login runs tmux with `TERM=xterm-256color`. ContainerSSH does not pass the client's environment to the pod in this setup, and tmux will not start without `TERM`.
- The pod's time zone and locale come from the `TZ` and `LANG` entries under `env` in `deploy/kubernetes/agentainer/statefulset.yaml` (`UTC` and `C.UTF-8`, the image defaults). tmux in the pod reads them from the container environment, since ContainerSSH does not pass the client's. To change them, edit the values, for example to `America/Denver` and `en_US.UTF-8`. An explicit `env` entry overrides the same name in the `agentainer-credentials` Secret, which the container loads with `envFrom` ([Pod API reference](https://kubernetes.io/docs/reference/kubernetes-api/workload-resources/pod-v1/): "Values defined by an Env with a duplicate key will take precedence."). This is the opposite of the launcher's env-file rule. To set `TZ` or `LANG` in the Secret, delete the matching `env` entries.
- ContainerSSH sends an SSH keepalive every 30 seconds, so load balancer and NAT idle timers do not drop a quiet session.
- To sign in to the agents from an SSH session, see [Signing in over SSH](logins.md#signing-in-over-ssh).

The agent pod has startup and readiness probes with a three-minute startup allowance. They execute the image's local health command; legacy images fall back to the active-tools link. These checks do not detect every hung agent. A liveness policy needs a separate responsiveness and recovery contract ([probe semantics](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)).

## SFTP and port forwarding

The image contains `sftp-server` (`/usr/lib/openssh/sftp-server`) and the ContainerSSH guest agent (`containerssh-agent`), which ContainerSSH needs for port forwarding. The example webhook keeps both features closed until you turn them on.

Closed, which is the default, an SFTP client gets "subsystem request failed on channel 0", and `ssh -L` and `ssh -D` get "open failed: administratively prohibited: Forwarding is rejected" (cluster check, 2026-11-04).

### The switch

The ConfigMap `agentainer-features` in the `containerssh` namespace ([`auth-webhook/features.yaml`](../deploy/kubernetes/auth-webhook/features.yaml)) holds two settings:

| Setting | Values | Effect |
|---|---|---|
| `sftp` | `on` or `off` | `on` allows the `sftp` subsystem and no other subsystem |
| `forwarding` | `local` or `off` | `local` allows `ssh -L` and `ssh -D`. Reverse (`ssh -R`), socket and X11 forwarding stay off. |

A missing setting is off. A malformed line, an unknown name or value, a repeated name, or a file over 4096 bytes turns both off. The webhook never fails open.

To turn SFTP and forwarding on, edit the ConfigMap:

```sh
kubectl -n containerssh edit configmap agentainer-features
```

and change the `features` value to:

```text
sftp=on
forwarding=local
```

To turn them off again, set both back to `off` the same way.

- The webhook reads the file on every new SSH connection, so the next connection gets the new settings. Open connections keep theirs. Nothing restarts: not the agent pod, its tmux session, ContainerSSH or the webhook.
- The change reaches the webhook pod when the kubelet updates the mounted ConfigMap, which "can be as long as the kubelet sync period + cache propagation delay" ([Mounted ConfigMaps are updated automatically](https://kubernetes.io/docs/concepts/configuration/configmap/#mounted-configmaps-are-updated-automatically)). In the cluster check it took 59 s and 75 s to open and 16 s to close.
- **`kubectl apply -k deploy/kubernetes` resets `agentainer-features` to the values in `features.yaml`.** A change made with `kubectl edit` lasts until the next apply. To keep a setting, change `features.yaml` in your copy of the repo, or patch it in your GitOps overlay.

### SFTP

- The subsystem runs as the `agent` user and reaches every file that user can, not only `~/transfer`.
- The subsystem setting takes no arguments, so you cannot choose the starting directory. Not verified: which directory a session starts in. The image's working directory is `/workspace` (`WORKDIR` in the `Containerfile`), and the cluster check used absolute paths only. Use absolute paths, for example `put report.pdf /home/agent/transfer/report.pdf`.
- With SFTP on, `sftp` works. The default `scp` uses the SFTP protocol since OpenSSH 9.0, so it needs SFTP on too; this is not verified. `scp -O` (the legacy protocol) and `rsync -e ssh` run as commands and should work without the switch; this is not verified either.
- The cluster check ran `put`, `get` and `ls` in `/home/agent/transfer`, and the downloaded file matched.

### Port forwarding

```sh
ssh -L 3000:localhost:3000 dev@<containerssh service address>   # a dev server in the pod
ssh -D 1080 dev@<containerssh service address>                  # a SOCKS proxy
```

- `forwarding=local` allows `ssh -L` to any host and port the pod can reach, and `ssh -D` as a SOCKS proxy. The reach is the same as a shell in the pod. The [network policy](#network-policy) decides what that is.
- ContainerSSH has no port filter. Its forwarding settings are only enable or disable ([forwarding reference](https://containerssh.io/v0.6/reference/forwarding/)), so a port allowlist is not possible.
- The cluster check reached a service on `127.0.0.1` in the pod through both `ssh -L` and `ssh -D` (SOCKS5).
- ContainerSSH logs "[Connection error io: read/write on closed pipe]" at the warning level when each forwarded channel closes. The data was delivered; the message is harmless.

## File transfer and FileBrowser

The pod mounts `agentainer-transfer` twice. Subpath `files` is `~/transfer` (`/home/agent/transfer`) in the agent container and the folder FileBrowser serves. Subpath `filebrowser` holds FileBrowser's database and cache. `~/transfer` exists only in this example. With the local launcher, move files through the bind-mounted `/workspace` instead.

To hand a screenshot to an agent, upload it to `~/transfer` and give the agent its path, for example `/home/agent/transfer/screenshot.png`.

[FileBrowser Quantum](https://github.com/gtsteffaniak/filebrowser) is a web file manager. The example pins the `2.0-stable-slim` tag by digest (`FILEBROWSER_IMAGE` in `versions.env`); the settings and behavior described here were checked against the v2.0.2-stable source. The example runs it as the second container, so ContainerSSH still opens sessions in the agent container. Its settings are in [`agentainer/filebrowser-config.yaml`](../deploy/kubernetes/agentainer/filebrowser-config.yaml). It listens on `127.0.0.1:8080` only and has no Service. Reach it through the API server:

```sh
kubectl -n agentainer port-forward pod/agentainer-0 8080:8080
```

Then open `http://127.0.0.1:8080` on your machine. In the cluster check a connection to the pod's IP on 8080 was refused.

First login:

1. Read the generated admin password. FileBrowser logs it once, on the first start of a new database:

   ```sh
   kubectl -n agentainer logs agentainer-0 -c filebrowser | grep 'initial admin password'
   ```

2. Log in as `admin` with it. FileBrowser then requires a new password. The ConfigMap sets the minimum length to 12 characters (`auth.methods.password.minLength`).

The database lives on the transfer volume, so the account and its new password survive a pod restart, and no new password is generated. Do not set `FILEBROWSER_ADMIN_PASSWORD`: FileBrowser applies it to the admin account on every start, which undoes a password changed in the UI. WebDAV is off. Analytics is a database setting that is off by default (`GET /api/settings/analytics` returned `{"enabled":false}` in the cluster check). Changes to the ConfigMap take effect after the pod restarts.

Security:

- **FileBrowser is not a security boundary against the agent container.** Both containers share the pod's network namespace, so anything running in the agent container can reach `127.0.0.1:8080` (confirmed in the cluster check). Give the admin account a unique password that the agent never sees. FileBrowser limits login attempts per client address and per username, and after 8 failed logins in a row from one address for one username it refuses that pair for 15 minutes (`authFailedLoginMaxAttempts` and `authFailedLoginLockoutMins` in `backend/internal/web/http.go` at v2.0.2-stable; `disableRateLimit` in the [HTTP settings](https://filebrowserquantum.com/en/docs/configuration/http/) turns this off). The lockout is not per account. Through `kubectl port-forward` your browser arrives from `127.0.0.1`, the same address as anything in the agent container, so failed logins from the agent can lock you out of `admin` for 15 minutes.
- **An upload can follow a link the agent planted.** The agent can replace a folder inside `~/transfer` with a symbolic link to a folder elsewhere, at any time. In the cluster check, with the example's `ignoreSymlinks` rule on, a new file uploaded through the API into the link's path was written to the link's target, a folder in FileBrowser's container. Reading through the link returned 403 ("resolved path escapes scope"), and overwriting an existing file through it failed with 404. The agent cannot read FileBrowser's folders, so it gets nothing back, but your file lands in the wrong place. In a local test of the same image and settings, the rule kept links out of FileBrowser's listings, so a folder that FileBrowser still lists is a real folder at that moment. FileBrowser resolves the folder when the upload arrives, so upload to the top of `~/transfer`, or reload the listing and confirm the folder is still there right before you upload. This is a limitation of FileBrowser, not fixed here. If you can, report it to the [FileBrowser Quantum project](https://github.com/gtsteffaniak/filebrowser/issues).

Single sign-on through a reverse proxy uses FileBrowser's proxy login, which the ConfigMap shows in a comment. It needs a listen address other than `127.0.0.1`, a Service of its own that only the proxy can reach, and a proxy that sets the username header and strips it from client requests ([proxy login](https://filebrowserquantum.com/en/docs/configuration/authentication/proxy/)).

## Shared memory

The agent container mounts a 1 Gi memory-backed `emptyDir` at `/dev/shm` for Chromium ([browser testing](browser-testing.md#shared-memory-and-network-access)). Files in it count against the agent container's memory limit, 8 Gi in the example ([emptyDir](https://kubernetes.io/docs/concepts/storage/volumes/#emptydir)).

## Limits

- The webhook gives each request a ten-second deadline for headers and body. It runs at most 16 handler threads and answers further connections with HTTP 503 ([implementation](../deploy/kubernetes/auth-webhook/webhook.py)).
- A cluster has no host folder. Clone repos into `/workspace`. **Work you have not pushed exists only on the workspace volume.**
- SFTP and port forwarding are off until you [switch them on](#the-switch). Reverse, socket and X11 forwarding are always off.
- The `agentainer-transfer` volume is one ReadWriteOnce claim, so the example runs one replica.
- The ContainerSSH-to-webhook traffic is plain HTTP inside the cluster. The example has no server-side TLS configuration; adding it requires a server change or TLS-terminating proxy. ContainerSSH's webhook client accepts `cacert`, `cert` and `key` settings for TLS (`config/http.go` in ContainerSSH v0.6.0).
- Resource requests and limits on all pods are example values. FileBrowser requests 50m CPU and 64 Mi memory and is limited to 500m and 256 Mi.
- [Kandev](extras.md#kandev), an optional extra, listens on `0.0.0.0` by default, and its local mode is "not an authenticated multi-user boundary". In the pod, start it with `KANDEV_SERVER_HOST=127.0.0.1` and reach it with `kubectl -n agentainer port-forward pod/agentainer-0 38429:38429` ([Kandev CLI, Ports and network exposure](https://kandev.ai/docs/cli)). Not verified in a cluster.
- To turn sudo on, follow the comment in [`agentainer/statefulset.yaml`](../deploy/kubernetes/agentainer/statefulset.yaml). The capability list there is untested, and the pod then needs the Baseline profile.

## SSH port access

- `loadBalancerSourceRanges` limits only traffic that arrives at the load balancer address. A `LoadBalancer` Service also opens a node port (from 30000-32767 by default) on every node, and kube-proxy does not apply the source ranges to it (`pkg/proxy/iptables/proxier.go` in Kubernetes v1.34.0). Anyone who can reach the node that runs the ContainerSSH pod can reach SSH through that port. Block the node port range from untrusted networks with a firewall in front of the nodes.
- If your load balancer sends traffic straight to pods instead of through node ports, you can set `allocateLoadBalancerNodePorts: false` in the Service, and Kubernetes allocates no node port for it ([Service docs](https://kubernetes.io/docs/concepts/services-networking/service/#load-balancer-nodeport-allocation)). The example does not set it, because a load balancer that routes through node ports stops working without them. Check your provider's documentation before you set it.
- The Service uses `externalTrafficPolicy: Local`, so ContainerSSH sees and logs the client's real address instead of a node address ([Preserving the client source IP](https://kubernetes.io/docs/tasks/access-application-cluster/create-external-load-balancer/#preserving-the-client-source-ip)). The load balancer sends traffic only to nodes that run the ContainerSSH pod.
- To use the commented `NodePort` alternative, change `type` and delete the `loadBalancerSourceRanges` line. The API server rejects a `NodePort` Service that sets it. Restrict access to the node port with a firewall. Connect with `ssh -p <node port>` to the node that runs the ContainerSSH pod; other nodes do not forward the port.

## Seeding a new home

The StatefulSet mounts an optional ConfigMap named `agentainer-seed` at `/etc/agentainer/seed`. When the pod starts, the entrypoint copies `AGENTS.md` and `mcp.json` from it to `~/.agentainer/AGENTS.md` and `~/.agentainer/mcp.json`, but only when that file is missing in the home volume. It never replaces a file that exists, so edits made in the pod survive restarts, and a changed ConfigMap does not reach a home that already has the file. Without the ConfigMap the pod starts as usual and gets the image's default `AGENTS.md`.

```sh
kubectl -n agentainer create configmap agentainer-seed \
  --from-file=AGENTS.md=./AGENTS.md --from-file=mcp.json=./mcp.json
```

Both keys are optional. [Configuration](configuration.md) describes both files; the entrypoint registers the servers in `mcp.json` with each agent. Create the ConfigMap before the first start of a new home volume, or delete the file in the pod and restart the pod to seed it again.

## Network policy

The example has two optional policies in `deploy/kubernetes/agentainer/`. Both are off by default and need a CNI that enforces NetworkPolicy. To use one, uncomment it in that folder's `kustomization.yaml`.

[`networkpolicy.yaml`](../deploy/kubernetes/agentainer/networkpolicy.yaml) limits the agent pod's outbound traffic:

- Allowed: DNS on UDP and TCP port 53 to every destination, and TCP port 443 to `0.0.0.0/0` and `::/0`.
- Excluded from the 443 rules: `10.0.0.0/8`, `172.16.0.0/12` and `192.168.0.0/16` (private IPv4), `100.64.0.0/10` (shared address space), `169.254.0.0/16` (link-local, which includes the cloud instance metadata address `169.254.169.254`), `fc00::/7` (IPv6 unique local) and `fe80::/10` (IPv6 link-local).
- Plain HTTP on port 80 is blocked everywhere.
- An API server or in-cluster HTTPS service at one of the excluded addresses is unreachable from the agent pod unless another rule allows it. One at a public address stays reachable on 443. ContainerSSH makes its own API server connection from its own pod, so SSH sessions keep working.
- DNS is not restricted, and the policy matches addresses and ports, not names ([Kubernetes policy semantics](https://kubernetes.io/docs/concepts/services-networking/network-policies/)).

To reach one internal service, add a narrow rule, for example in a second policy, since policies add up:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: agentainer-egress-internal, namespace: agentainer}
spec:
  podSelector: {matchLabels: {app: agentainer}}
  policyTypes: [Egress]
  egress:
    - to: [{ipBlock: {cidr: 203.0.113.10/32}}]
      ports: [{protocol: TCP, port: 443}]
```

In the cluster check, with the policy on, HTTPS to a private pod address timed out, while `https://example.com`, the npm registry and the Playwright download CDN worked. A second policy like the one above re-allowed the private address.

[`ingress-policy.yaml`](../deploy/kubernetes/agentainer/ingress-policy.yaml) denies all ingress to the agent pod. SSH sessions use the Kubernetes API (`pods/exec`), and `kubectl port-forward` goes through the API server and the kubelet. Not verified: that SSH and `kubectl port-forward` keep working with this policy on. The cluster check did not apply it, and how the kubelet's port-forward traffic meets NetworkPolicy depends on the CNI.

Without the egress policy, the agent pod can reach any address, including the instance metadata address if the cluster allows it.

## Your own config server

If you replace the example webhook with your own ContainerSSH config server, it decides SFTP and forwarding.

- **Deny the `sftp` subsystem** unless you want it. ContainerSSH maps `sftp` to `/usr/lib/openssh/sftp-server` by default and allows subsystems by default (`Subsystems` in `config/kubernetes.go` at ContainerSSH v0.6.0), and this image now contains that program. Set `security.subsystem.mode` to `disable`, or to `filter` with an `allow` list ([security reference](https://containerssh.io/v0.6/reference/security/)).
- ContainerSSH's default `agentPath` is `/usr/bin/containerssh-agent` (`AgentPath` in `config/kubernetes.go` at ContainerSSH v0.6.0). The image installs the agent at `/usr/local/bin/containerssh-agent` and links it at that default path, so forwarding works without setting `agentPath`.
- ContainerSSH disables forwarding by default ([forwarding reference](https://containerssh.io/v0.6/reference/forwarding/)).

## Upgrading and removing

To upgrade, change `newTag` in `agentainer/kustomization.yaml` and run `kubectl apply -k deploy/kubernetes`. After a stable release publishes `latest`, using `newTag: latest` means the manifest does not change, so restart the pod instead: `kubectl -n agentainer rollout restart statefulset agentainer`. The `home` and `workspace` volumes stay. Each apply also resets the [SFTP and forwarding switch](#the-switch).

The transfer volume is a separate PersistentVolumeClaim, not a `volumeClaimTemplate`, because Kubernetes refuses changes to `volumeClaimTemplates` on an existing StatefulSet. In the cluster check, applying this example over the previous one succeeded, created `agentainer-transfer` and rolled out both containers.

The StatefulSet keeps the `home` and `workspace` PVCs when it is deleted or scaled down. **`kubectl delete -k deploy/kubernetes` deletes the `agentainer` namespace, which deletes those PVCs and `agentainer-transfer` and, with the usual `Delete` reclaim policy, the disks.** To keep your work, delete only the StatefulSet (`kubectl -n agentainer delete statefulset agentainer`), or set the volumes' reclaim policy to `Retain` first.

Every object in `deploy/kubernetes` carries the label `app.kubernetes.io/part-of: agentainer`; the Pods and the PVCs created from the templates do not. To list the labelled objects:

```sh
kubectl get namespace,statefulset,deployment,service,configmap,serviceaccount,role,rolebinding,networkpolicy,persistentvolumeclaim \
  -A -l app.kubernetes.io/part-of=agentainer
```

## Troubleshooting

- **Short external names resolve to the wrong address.** Pods use `ndots:5` by default ([DNS for Services and Pods](https://kubernetes.io/docs/concepts/services-networking/dns-pod-service/)). If a node's resolv.conf search list includes a domain with wildcard DNS records, a name such as `go.dev` can resolve to that domain's address first, and the egress policy may then block it. Set this in the pod template of `statefulset.yaml`:

  ```yaml
  dnsConfig:
    options: [{name: ndots, value: "1"}]
  ```

- **FileBrowser shows no initial password.** It logs the password only when it creates a new database, so a restart with an existing database prints none.
- **"Connection error io: read/write on closed pipe" in the ContainerSSH log** after a forwarded connection closes is harmless.

## More than one user

The example serves one user. Multi-user support is not built; it would need these changes:

- The webhook's `/config` answer would name a per-user pod such as `agentainer-<user>-0`.
- Each user would get a StatefulSet and volumes, and `authorized_keys` would become a per-user mapping. The transfer volume would need to be per user too.
- The ContainerSSH Role lists only `agentainer-0` in `resourceNames`. Add each per-user pod to both rules, or give each user a namespace with its own Role and RoleBinding for the ContainerSSH ServiceAccount.

The image stays the same.
