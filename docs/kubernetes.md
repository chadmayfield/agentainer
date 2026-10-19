# Kubernetes with ContainerSSH

[`deploy/kubernetes/`](../deploy/kubernetes/) has an example you apply with `kubectl apply -k`. You reach the agent pod over SSH through [ContainerSSH](https://containerssh.io/v0.6/) v0.6.0, and each login lands in the same tmux session.

- Namespace `agentainer`: a StatefulSet with one pod, `agentainer-0`, and two volumes, `home` (20 Gi) and `workspace` (50 Gi). It meets the [Restricted Pod Security Standard](https://kubernetes.io/docs/concepts/security/pod-security-standards/), mounts no service account token, and keeps sudo off.
- Namespace `containerssh`: the ContainerSSH server in [persistent mode](https://containerssh.io/v0.6/reference/kubernetes/#persistent-mode), and a small Python webhook that checks SSH public keys and tells ContainerSSH which pod to use. A NetworkPolicy lets only ContainerSSH reach the webhook, if your CNI enforces NetworkPolicy.
- The ContainerSSH image on Docker Hub is amd64 only, so its Deployment runs on amd64 nodes. The agentainer pod runs on either architecture.

This example has not been deployed to a cluster yet.

## Install

Before you apply, set `loadBalancerSourceRanges` in [`containerssh/service.yaml`](../deploy/kubernetes/containerssh/service.yaml) to your client range, and pin the image in [`agentainer/kustomization.yaml`](../deploy/kubernetes/agentainer/kustomization.yaml) (`images`, `newTag`). The example follows `latest`.

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
- ContainerSSH sends an SSH keepalive every 30 seconds, so load balancer and NAT idle timers do not drop a quiet session.

## Limits

- A cluster has no host folder. Clone repos into `/workspace`. **Work you have not pushed exists only on the workspace volume.**
- sftp and the default `scp` do not work: since OpenSSH 9.0, `scp` uses the SFTP protocol, and the image has no `sftp-server`. `scp -O` (the legacy protocol) and `rsync -e ssh` should work, because ContainerSSH runs those as commands; this is not verified.
- Port forwarding (`ssh -L`, `ssh -R`), socket forwarding and X11 forwarding are off: ContainerSSH disables them by default and the example keeps that.
- The Service uses `externalTrafficPolicy: Local`, so ContainerSSH and `loadBalancerSourceRanges` see the client's real address. If you switch to the commented `NodePort` alternative, connect to the node that runs the ContainerSSH pod; other nodes do not forward the port.
- The ContainerSSH-to-webhook traffic is plain HTTP inside the cluster. ContainerSSH's webhook client accepts `cacert`, `cert` and `key` settings for TLS (`config/http.go` in ContainerSSH v0.6.0).
- Resource requests and limits on all three pods are example values.
- To turn sudo on, follow the comment in [`agentainer/statefulset.yaml`](../deploy/kubernetes/agentainer/statefulset.yaml). The capability list there is untested, and the pod then needs the Baseline profile.

## Network policy

[`agentainer/networkpolicy.yaml`](../deploy/kubernetes/agentainer/networkpolicy.yaml) allows the agent pod only DNS (port 53) and outbound TCP 443. It is off by default; add it to that folder's `kustomization.yaml` to use it, with a CNI that enforces NetworkPolicy. Without it, the agent pod can reach any address, including your cloud provider's instance metadata address (`169.254.169.254`) if the cluster allows it.

## Upgrading and removing

To upgrade, change `newTag` in `agentainer/kustomization.yaml` and run `kubectl apply -k deploy/kubernetes`. The `home` and `workspace` volumes stay.

The StatefulSet keeps the `home` and `workspace` PVCs when it is deleted or scaled down. **`kubectl delete -k deploy/kubernetes` also deletes the `agentainer` namespace, which deletes those PVCs and, with the usual `Delete` reclaim policy, the disks.** To keep your work, delete only the StatefulSet (`kubectl -n agentainer delete statefulset agentainer`), or set the volumes' reclaim policy to `Retain` first.

Every object in `deploy/kubernetes` carries the label `app.kubernetes.io/part-of: agentainer`; the Pods and PVCs created from them do not. To list the labelled objects:

```sh
kubectl get namespace,statefulset,deployment,service,configmap,serviceaccount,role,rolebinding,networkpolicy \
  -A -l app.kubernetes.io/part-of=agentainer
```

## More than one user

Multi-user is a documented path, not built:

- The webhook's `/config` answer would name a per-user pod such as `agentainer-<user>-0`.
- Each user would get a StatefulSet and volumes, and `authorized_keys` would become a per-user mapping.
- The ContainerSSH Role lists only `agentainer-0` in `resourceNames`. Add each per-user pod to both rules, or give each user a namespace with its own Role and RoleBinding for the ContainerSSH ServiceAccount.

The image stays the same.
