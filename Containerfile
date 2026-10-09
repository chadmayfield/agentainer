# AgentBox image. Build with scripts/build.sh so BASE_IMAGE and APT_SNAPSHOT come from versions.env.
ARG BASE_IMAGE

# Throwaway stage: the base image has no CA bundle and snapshot.ubuntu.com is https.
# Only the bundle file leaves this stage; every package in the final image comes
# from the snapshot.
FROM ${BASE_IMAGE} AS certs
RUN apt-get update \
	&& DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates

FROM ${BASE_IMAGE}

ARG TARGETARCH
ARG APT_SNAPSHOT
ARG UID=1000
ARG GID=1000
# Podman honours SHELL only with --format docker, which scripts/build.sh passes.
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

# Guard: stop the build unless RUN steps use bash with errexit and pipefail.
RUN [ -n "${BASH_VERSION:-}" ] && [[ $- == *e* ]] && set -o | grep -Eq '^pipefail[[:space:]]+on' \
	&& mkdir -p /usr/local/share/agentbox \
	&& echo "bash ${BASH_VERSION} errexit pipefail" > /usr/local/share/agentbox/build-shell.txt

COPY --from=certs /etc/ssl/certs/ca-certificates.crt /tmp/agentbox-build/ca.crt
COPY build/apt-packages.txt build/check-apt-snapshot.py /tmp/agentbox-build/

# apt packages from the pinned Ubuntu snapshot (spec 4.1).
# - Both architectures use archive.ubuntu.com: the arm64 image defaults to
#   ports.ubuntu.com, which the snapshot service does not cover, while
#   archive.ubuntu.com serves resolute arm64 and has snapshots.
# - A "Snapshot: <ID>" field in each source (apt sources.list(5)) pins apt.
# - upgrade brings the base image's own packages to their snapshot versions.
#   Always-Include-Phased-Updates makes upgrades take the same (newest) versions
#   that fresh installs already get, instead of deferring phased ones
#   (apt_preferences(5), "Phased Updates").
# - check-apt-snapshot.py fails the build if any installed version is not in the snapshot.
RUN test -n "${APT_SNAPSHOT}" \
	&& export DEBIAN_FRONTEND=noninteractive \
	&& printf 'Types: deb\nURIs: http://archive.ubuntu.com/ubuntu/\nSuites: resolute resolute-updates resolute-backports\nComponents: main universe restricted multiverse\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\nSnapshot: %s\n\nTypes: deb\nURIs: http://security.ubuntu.com/ubuntu/\nSuites: resolute-security\nComponents: main universe restricted multiverse\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\nSnapshot: %s\n' "${APT_SNAPSHOT}" "${APT_SNAPSHOT}" > /etc/apt/sources.list.d/ubuntu.sources \
	&& APT="apt-get -o Acquire::https::CAInfo=/tmp/agentbox-build/ca.crt -o APT::Get::Always-Include-Phased-Updates=true" \
	&& $APT update \
	&& $APT upgrade -y \
	&& xargs -a /tmp/agentbox-build/apt-packages.txt $APT install -y --no-install-recommends \
	&& mkdir -p /usr/local/share/agentbox \
	&& apt-cache policy bash > /usr/local/share/agentbox/apt-policy.txt \
	&& python3 /tmp/agentbox-build/check-apt-snapshot.py /usr/local/share/agentbox/apt-unpinned.txt \
	&& sed -i '/^Snapshot: /d' /etc/apt/sources.list.d/ubuntu.sources \
	&& rm -rf /var/lib/apt/lists/*

# Debian names these binaries fdfind and batcat (package file lists, spec 4.1).
# ping ships with the cap_net_raw file capability, which fails under runtimes that
# drop NET_RAW (Podman's default, the Kubernetes example). Without it, ping uses an
# unprivileged ICMP socket, allowed by the net.ipv4.ping_group_range sysctl that the
# launcher and the pod spec set.
RUN ln -s /usr/bin/fdfind /usr/local/bin/fd \
	&& ln -s /usr/bin/batcat /usr/local/bin/bat \
	&& python3 -c 'import os; os.removexattr("/usr/bin/ping", "security.capability")'

# Rename the base image's ubuntu user (UID 1000) to agent (spec 16.2). With other
# build args, reuse a group that already has GID (for example 20, which is
# "dialout" in Ubuntu and "staff" on macOS).
RUN if [ "${UID}" = 1000 ] && [ "${GID}" = 1000 ]; then \
		groupmod -n agent ubuntu \
		&& usermod -l agent -d /home/agent -m -c AgentBox -G "" ubuntu; \
	else \
		userdel -r ubuntu 2>/dev/null || true; \
		getent group "${GID}" >/dev/null || groupadd -g "${GID}" agent; \
		useradd -m -u "${UID}" -g "${GID}" -s /bin/bash -c AgentBox agent; \
	fi \
	&& printf 'agent ALL=(ALL) NOPASSWD:ALL\n' > /etc/sudoers.d/agent \
	&& chmod 0440 /etc/sudoers.d/agent \
	&& install -d -o agent -g "${GID}" /workspace

ENV LANG=C.UTF-8

# Copied after the apt layer so a pin bump for other tools does not rerun apt.
COPY versions.env /usr/local/share/agentbox/versions.env

COPY build/fetch.sh build/install-upstream.sh /tmp/agentbox-build/
RUN TARGETARCH="${TARGETARCH}" bash /tmp/agentbox-build/install-upstream.sh

ENV RUSTUP_HOME=/opt/rustup \
	PATH=/usr/local/go/bin:/opt/cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

RUN rm -rf /tmp/agentbox-build

USER agent
WORKDIR /workspace
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sleep", "infinity"]
