# k3s-dhbw-cloud-role

Ansible Role for the installation and configuration of a production-ready K3s cluster, specifically optimized for the infrastructure requirements of the [DHBW Cloud](https://dhbw.cloud) (only accessible from the DHBW network).

This role automates the bootstrapping of Linux hosts and the deployment of essential cloud-native components:
- **K3s:** Lightweight Kubernetes distribution (server or agent mode).
- **CNI:** k3s' built-in flannel (plus kube-proxy and the network-policy controller) — the k3s defaults; works in IPv4, IPv6 and dual-stack on a single interface (see [CNI: flannel](#cni-flannel)).
- **NGINX Ingress Controller:** For external routing of traffic (optional, can be disabled in favour of the built-in Traefik).
- **Cert-Manager:** For automated issuance and renewal of TLS certificates (ACME).
- **ExternalDNS:** For automatic management of DNS records (supports RFC2136/TSIG).
- **Longhorn:** Distributed, replicated block storage for node-independent volumes (optional, off by default — recommended for multi-node clusters).

---

## Installation

Add the role to your requirements file (`requirements.yml`):

```yaml
---
- name: k3s-dhbw-cloud-role
  src: https://github.com/pfisterer/k3s-dhbw-cloud-role.git
  # version: main
  # version: v1.0.0
```

Then install it:

```bash
ansible-galaxy install -r requirements.yml
```

---

## Usage

### Single-node (default)

The simplest case — one host, full k3s server with all add-ons. No extra configuration needed.

**`inventory.yml`**
```yaml
all:
  hosts:
    "1.2.3.4":
      ansible_user: ubuntu
      ip_family: ipv4
      cert_manager_email: your@mail.com
```

**`playbook.yml`**
```yaml
---
- name: Deploy K3s
  hosts: all
  become: true
  roles:
    - role: k3s-dhbw-cloud-role
```

---

### Multi-node (server + agents)

For clusters with worker nodes, structure your inventory using host groups so Ansible can enforce server-before-agent ordering and pass the join token automatically.

**`inventory.yml`**
```yaml
all:
  children:

    # -----------------------------------------------------------------------
    # PRODUCTION
    # -----------------------------------------------------------------------
    production:
      children:
        production_k3s_server:
          vars:
            k3s_role: server
          hosts:
            "141.72.5.244":
              ansible_user: root
              ip_family: ipv4
              cert_manager_email: your@mail.com
              # ... all other role variables ...

        production_k3s_agent:
          vars:
            k3s_role: agent
            k3s_server_host: "141.72.5.244"   # must match the server host above
          hosts:
            "141.72.5.101":
              ansible_user: root
            "141.72.5.102":
              ansible_user: root

    # -----------------------------------------------------------------------
    # STAGING
    # -----------------------------------------------------------------------
    staging:
      children:
        staging_k3s_server:
          vars:
            k3s_role: server
          hosts:
            "141.72.176.135":
              ansible_user: root
              ip_family: ipv4
              cert_manager_email: your@mail.com
              # ... all other role variables ...

        staging_k3s_agent:
          vars:
            k3s_role: agent
            k3s_server_host: "141.72.176.135"
          hosts:
            "141.72.176.201":
              ansible_user: root
```

**`playbook.yml`**
```yaml
---
- name: Deploy K3s
  hosts: all
  become: true
  roles:
    - role: k3s-dhbw-cloud-role
```

The role detects each host's role via `k3s_role`. Server and agent tasks run in the same play — agent nodes automatically wait for the server to finish writing its join token before proceeding, so no manual ordering or token passing is needed.

Run a single environment:

```bash
ansible-playbook playbook.yml -i inventory.yml --limit staging
ansible-playbook playbook.yml -i inventory.yml --limit production
```

---

### IPv6 and dual-stack

The role works in IPv4-only, IPv6-only and dual-stack environments. The stack is
selected with `ip_family`; in dual-stack `ip_family_primary` decides which family
is preferred (listed first in the cluster/service CIDRs and `--node-ip`, and used
for the externally advertised address). The externally reachable IP is taken
automatically from the address Ansible connects through — no manual configuration
needed in the common case.

**Dual-stack, IPv4 primary** (IPv6 as an add-on):
```yaml
"141.72.5.244":
  ansible_user: root
  ip_family: dual
  ip_family_primary: ipv4
  cert_manager_email: your@mail.com
```

**Dual-stack, IPv6 primary** (e.g. only private/NATed IPv4, public IPv6):
```yaml
"2001:db8::1":          # connect over the public IPv6 address
  ansible_user: root
  ip_family: dual
  ip_family_primary: ipv6
  cert_manager_email: your@mail.com
```

**IPv6-only:**
```yaml
"2001:db8::1":
  ansible_user: root
  ip_family: ipv6
  cert_manager_email: your@mail.com
```

Notes:
- In IPv6-only / NAT setups, prefer the DNS-01 challenge (`cert_manager_preferred_challenge: dns01`, requires the RFC2136 variables) over HTTP-01, since the ACME server must otherwise reach the ingress over the chosen family.
- ExternalDNS manages `A`, `AAAA` and `CNAME` records, so IPv6 ingress addresses are published automatically.
- The default IPv6 pod/service CIDRs are ULA ranges (`fd00:42::/56` / `fd00:43::/112`); override `k3s_cluster_cidr_ipv6` / `k3s_service_cidr_ipv6` to use routed (GUA) prefixes.

---

## CNI: flannel

This role uses k3s' built-in **flannel** CNI — the k3s default — together with kube-proxy and the network-policy controller. No extra CNI install or teardown steps are required (`k3s-killall.sh` / `k3s-uninstall.sh` work as-is). The only CNI-related install flag the role adds is `--flannel-ipv6-masq`, and only when IPv6 is in use, so ULA (`fd00::/8`) pods can still egress.

flannel's single-device VXLAN handles IPv4, IPv6 and dual-stack fine when every family lives on **one** interface. It cannot route two families that live on *different* interfaces (a split-NIC setup, e.g. routable IPv6 on one NIC and NATed IPv4 on another) — for that topology you'd need a CNI that can route each family out its own interface. See the [k3s networking guide](https://docs.k3s.io/networking/basic-network-options).

---

## Storage

By default k3s ships Rancher's **`local-path`** provisioner as the default StorageClass. It is **node-local**: a PVC is provisioned as a directory on whichever node the first consuming pod lands on, and the resulting PV is pinned to that node. That is fine for a single node, but in a **multi-node** cluster it means:

- A pod that gets rescheduled to another node (drain, node failure) cannot reach its data and stays `Pending` — there is **no failover**.
- Only `ReadWriteOnce` is supported (no `ReadWriteMany`).

For real multi-node persistence, enable **Longhorn** (`longhorn_enabled: true`), which provides replicated, node-independent block storage with `RWO`/`RWX`, snapshots and backups:

```yaml
longhorn_enabled: true
# longhorn_replica_count defaults to 1 (works on any cluster size, fine for labs);
# raise to 3 on a >= 3-node cluster for production redundancy.
longhorn_replica_count: 1
longhorn_default_storage_class: true   # makes Longhorn the default, unsets local-path's default
```

When enabled, the role installs the iSCSI/NFS node prerequisites (`open-iscsi`, `nfs-common`, `iscsid`) on **every** node automatically. Longhorn provides a `longhorn` StorageClass; with `longhorn_default_storage_class: true` it also removes the default flag from `local-path` so exactly one default StorageClass remains.

> Note: the k3s server still stores cluster state in a single-node datastore (`/var/lib/rancher/k3s/server`). Longhorn replicates **application** volumes, not the control-plane state — back up the server datastore separately.

---

## Variables

All variables are defined in `defaults/main.yml` and can be overridden per host or group.

### Node role

| Variable          | Default  | Description                                                                                                         |
| ----------------- | -------- | ------------------------------------------------------------------------------------------------------------------- |
| `k3s_role`        | `server` | Set to `agent` on worker nodes.                                                                                     |
| `k3s_server_host` | `""`     | IP of the server to join. Required when `k3s_role: agent`. The join token is fetched from the server automatically. |

### General / Networking

| Variable                | Default                     | Description                                                                                                                                                                                              |
| ----------------------- | --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ip_family`             | `ipv4`                      | IP stack to configure: `ipv4` (single-stack), `ipv6` (single-stack) or `dual` (dual-stack). Drives TLS SANs, kubeconfig URL, `--node-ip` and the pod/service CIDRs.                                      |
| `ip_family_primary`     | `ipv4`                      | Only used when `ip_family: dual` — which family is **primary** (listed first in the CIDRs / `--node-ip`). Use `ipv4` when IPv6 is just an add-on, `ipv6` when e.g. only private/NATed IPv4 is available. |
| `k3s_cluster_cidr_ipv4` | `10.42.0.0/16`              | IPv4 pod CIDR (k3s default).                                                                                                                                                                             |
| `k3s_service_cidr_ipv4` | `10.43.0.0/16`              | IPv4 service CIDR (k3s default).                                                                                                                                                                         |
| `k3s_cluster_cidr_ipv6` | `fd00:42::/56`              | IPv6 pod CIDR (ULA). Only applied when IPv6 is involved.                                                                                                                                                 |
| `k3s_service_cidr_ipv6` | `fd00:43::/112`             | IPv6 service CIDR (ULA). Only applied when IPv6 is involved.                                                                                                                                             |
| `k3s_node_external_ip`  | `""`                        | Externally reachable node IP (`--node-external-ip`). Empty = auto-detect from the address Ansible connects through (`ansible_host`) whenever it differs from the internal interface address (e.g. NAT).  |
| `k3s_exec_args`         | `""`                        | Set to a non-empty string to **fully override** the dynamically computed k3s server install arguments. Empty = use the computed args.                                                                    |
| `k3s_extra_exec_args`   | `""`                        | Extra arguments appended verbatim to the computed k3s server install arguments.                                                                                                                          |
| `ingress_nginx_enabled` | `true`                      | Set to `false` to skip NGINX Ingress Controller and keep the built-in Traefik instead. Also adjusts the cert-manager HTTP-01 solver class accordingly.                                                   |
| `kubeconfig_root`       | `/etc/rancher/k3s/k3s.yaml` | Path to the kubeconfig on the server node.                                                                                                                                                               |
| `kubeconfig_path`       | `""`                        | Where the server's kubeconfig is fetched on the control node (path + filename). Empty = default `./kubeconfig-<inventory_host>.yaml`. Set to a fixed path to always write/overwrite the same file.       |

### Storage (Longhorn)

| Variable                         | Default           | Description                                                                                                   |
| -------------------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------ |
| `longhorn_enabled`               | `false`           | Install Longhorn for replicated, node-independent volumes. Installs the iSCSI/NFS prerequisites on all nodes. |
| `longhorn_namespace`             | `longhorn-system` | Namespace Longhorn is deployed into.                                                                          |
| `longhorn_version`               | `""`              | Longhorn Helm chart version. Empty = latest; pin a tag (e.g. `1.7.2`) for reproducible installs.             |
| `longhorn_replica_count`         | `1`               | Default replicas per volume. Must be `<=` the number of nodes (asserted). `1` suits teaching/labs; raise to `3` (≥3 nodes) for production redundancy. |
| `longhorn_default_storage_class` | `true`            | Make Longhorn the default StorageClass and unset `local-path`'s default flag (so exactly one default exists). |

### Bootstrap / client tooling

These tools (Helm, kubectl, Skaffold, shell aliases and completions) are installed on the **server node only** — agents have no kubeconfig, so they would be unusable there.

| Variable                        | Default    | Description                                                                                                                          |
| ------------------------------- | ---------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `bootstrap_install_client_tools` | `true`     | Install Helm, kubectl, Skaffold and the shell aliases/completions on the server. Set to `false` for a lean node.                    |
| `helm_version`                  | `""`       | Helm version to install. Empty = latest stable; pin a tag (e.g. `v3.16.3`) for reproducible installs.                              |
| `kubectl_version`               | `""`       | kubectl version to install. Empty = latest stable (`stable.txt`); pin a tag (e.g. `v1.31.4`).                                       |
| `skaffold_version`              | `latest`   | Skaffold release to install (`latest` or a tag such as `v2.13.2`).                                                                  |

### Cert-Manager

| Variable                           | Default                           | Description                                                        |
| ---------------------------------- | --------------------------------- | ------------------------------------------------------------------ |
| `cert_manager_email`               | `""`                              | ACME account email. Leave empty to skip cert-manager installation. |
| `cert_manager_url`                 | `https://certificates.dhbw.cloud` | ACME server URL.                                                   |
| `cert_manager_namespace`           | `cert-manager`                    | Deployment namespace.                                              |
| `cert_manager_preferred_challenge` | `http01`                          | Challenge type: `http01` or `dns01`. `dns01` needs the RFC2136 vars (see ExternalDNS) and uses the role-created TSIG secret; falls back to `http01` if they are unset. |
| `cert_manager_rfc2136_tsig_secret_name` | `cert-manager-rfc2136-tsig`  | Name of the Secret the role creates (in the cert-manager namespace) holding the RFC2136 TSIG key for the `dns01` solver.                                              |
| `cert_manager_cluster_issuer_name` | `certificate-cluster-issuer`      | Name of the ClusterIssuer this role creates. Reference it from your Ingress/IngressRoute (e.g. the `cert-manager.io/cluster-issuer` annotation). |
| `cert_manager_private_key_secret_name` | `cert-manager-private-key-secret` | Secret name for the ACME account private key (`privateKeySecretRef`). |
| `cert_manager_eab_keyid`           | `""`                              | External Account Binding Key ID (optional).                        |
| `cert_manager_eab_secret`          | `""`                              | External Account Binding MAC key (optional).                       |
| `cert_manager_eab_secret_name`     | `cert-manager-eab-secret`         | Secret name holding the EAB MAC key (only used when EAB is set).   |

### ExternalDNS (RFC2136)

| Variable                           | Default                      | Description                                             |
| ---------------------------------- | ---------------------------- | ------------------------------------------------------- |
| `rfc2136_zone`                     | _(unset)_                    | DNS zone. Leave unset to skip ExternalDNS installation. |
| `rfc2136_dns_host`                 | `""`                         | RFC2136 DNS server IP. Required when `rfc2136_zone` is set (also used as the cert-manager `dns01` nameserver). |
| `rfc2136_dns_port`                 | `53`                         | RFC2136 DNS server port.                               |
| `rfc2136_tsig_secret_value`        | _(unset)_                    | TSIG secret value.                                      |
| `rfc2136_tsig_secret_alg`          | _(unset)_                    | TSIG algorithm (e.g. `hmac-sha512`).                    |
| `rfc2136_tsig_secret_keyname`      | _(unset)_                    | TSIG key name.                                          |
| `external_dns_namespace`           | `external-dns`               | Namespace ExternalDNS is deployed into.                 |
| `external_dns_log_level`           | `debug`                      | ExternalDNS log level.                                  |
| `external_dns_txt_owner_id`        | `dynamic-zones-dns`          | Owner ID written into the registry TXT records. Make this unique per cluster when several clusters share a zone. |
| `external_dns_txt_prefix`          | `dynamic-zones-dns-`         | Prefix for the registry TXT records.                    |
| `external_dns_exclude_target_nets` | _(RFC1918/CGNAT/ULA/link-local)_ | CIDRs ExternalDNS must never publish (e.g. private/NAT addresses on a dual-stack node). |
| `external_dns_version`             | `v0.19.0`                    | ExternalDNS Helm chart version.                         |

---

## Accessing the Cluster

After a successful run, the kubeconfig is fetched to the Ansible control node as:

```
./kubeconfig-<hostname>.yaml
```

Use it with:

```bash
export KUBECONFIG=./kubeconfig-141.72.5.244.yaml
kubectl get nodes
```
