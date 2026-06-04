# k3s-dhbw-cloud-role

An Ansible role that turns one or more Linux hosts into a ready-to-use [k3s](https://k3s.io) Kubernetes cluster for the [DHBW Cloud](https://dhbw.cloud) (reachable from the DHBW network).

The point of the role is that the fiddly parts — **DNS** and **TLS** — are handled for you. Once it has run, every app you deploy automatically gets:

- **A public DNS name** — for any Ingress with a hostname under your zone, [ExternalDNS](https://kubernetes-sigs.github.io/external-dns/) creates the DNS record for you.
- **Valid HTTPS** — [cert-manager](https://cert-manager.io) obtains and auto-renews a TLS certificate (one wildcard `*.<your-zone>` by default), so your app is reachable over HTTPS with no per-app setup.

You also get a full k3s cluster (one server, optional worker nodes), the built-in **Traefik** ingress, IPv4 / IPv6 / dual-stack support, and optional replicated storage ([Longhorn](https://longhorn.io)).

To use it you only need to supply: the **host(s)** to install on, and — for certificates and DNS — an **email** and a **DNS zone**.

---

## Installation

Add the role to your requirements file (`requirements.yml`):

```yaml
---
- name: k3s-dhbw-cloud-role
  src: https://github.com/pfisterer/k3s-dhbw-cloud-role.git
```

Then install it:

```bash
ansible-galaxy install -r requirements.yml
```

---

## Usage

### Single-node (default)

One host, full k3s server with all add-ons.

**`inventory.yml`**
```yaml
all:
  hosts:
    "1.2.3.4":
      ansible_user: ubuntu
      ip_family: ipv4
      cert_manager_email: your@mail.com

      # DNS + automatic (wildcard) TLS — set these to enable ExternalDNS and DNS-01.
      # Without them you still get a working cluster, just no automatic DNS/HTTPS.
      # DHBW: get your zone and TSIG key from https://self-service.dhbw.cloud
      rfc2136_zone: your-zone.example.com
      rfc2136_tsig_secret_value: "<TSIG key>"
      rfc2136_tsig_secret_alg: hmac-sha512
      rfc2136_tsig_secret_keyname: "<TSIG key name>"
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

### Exposing an app with DNS + TLS

This is the part you'll use most. Deploy your app, then create an **Ingress** with a hostname under your zone — DNS and HTTPS are then automatic:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: myapp
spec:
  rules:
    - host: myapp.your-zone.example.com      # must be under your rfc2136_zone
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: myapp
                port:
                  number: 80
  tls:
    - hosts: [myapp.your-zone.example.com]    # served by the cluster's wildcard certificate
```

What happens automatically:

- **DNS:** ExternalDNS sees the hostname and publishes the matching record.
- **HTTPS:** Traefik serves the cluster's wildcard certificate for any host under `*.your-zone.example.com` — you don't request a certificate per app.

Need a **dedicated** (non-wildcard) certificate for a host? Add the annotation `cert-manager.io/cluster-issuer: certificate-cluster-issuer` and a `secretName` to the `tls` entry, and cert-manager issues one just for that host.

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
- The DNS-01 challenge is the default (`cert_manager_preferred_challenge: dns01`, requires the RFC2136 variables) — it works in IPv6-only / NAT setups where the ACME server cannot otherwise reach the ingress over the chosen family, and it is the only challenge that can issue the wildcard certificate. It falls back to HTTP-01 when the RFC2136 variables are unset.
- ExternalDNS manages `A`, `AAAA` and `CNAME` records, so IPv6 ingress addresses are published automatically.
- The default IPv6 pod/service CIDRs are ULA ranges (`fd00:42::/56` / `fd00:43::/112`); override `k3s_cluster_cidr_ipv6` / `k3s_service_cidr_ipv6` to use routed (GUA) prefixes.

---
## Storage

k3s' built-in **`local-path`** storage puts a volume in a directory on the node where the pod first starts, and pins it there. That is fine for a **single node**, but on a **multi-node** cluster it means no failover (a pod rescheduled to another node can't reach its data) and `ReadWriteOnce` only.

So the role **enables Longhorn automatically on a multi-node cluster** (and leaves it off on a single node). Longhorn provides replicated, node-independent block storage with `RWO`/`RWX`, snapshots and backups. The role installs the required node packages (iSCSI/NFS) on every node and, by default, makes Longhorn the single default StorageClass (disabling `local-path`).

You can override the auto-detection and tune replication:

```yaml
longhorn_enabled: true                 # force on/off instead of auto-detecting from the node count
longhorn_replica_count: 1              # 1 works on any cluster size (labs); use 3 on a >= 3-node cluster
longhorn_default_storage_class: true   # make Longhorn the default StorageClass
```

> Note: Longhorn replicates **application** volumes, not the k3s control-plane state (`/var/lib/rancher/k3s/server`) — back that up separately.

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
| `kubeconfig_root`       | `/etc/rancher/k3s/k3s.yaml` | Path to the kubeconfig on the server node.                                                                                                                                                               |
| `kubeconfig_path`       | `""`                        | Where the server's kubeconfig is fetched on the control node (path + filename). Empty = default `./kubeconfig-<inventory_host>.yaml`. Set to a fixed path to always write/overwrite the same file.       |

### Storage (Longhorn)

| Variable                         | Default           | Description                                                                                                                                                                                                 |
| -------------------------------- | ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `longhorn_enabled`               | _auto_            | Install Longhorn for replicated, node-independent volumes. Auto: **on** for a multi-node run, **off** for a single node. Set `true`/`false` to override. Installs the iSCSI/NFS prerequisites on all nodes. |
| `longhorn_namespace`             | `longhorn-system` | Namespace Longhorn is deployed into.                                                                                                                                                                        |
| `longhorn_version`               | `""`              | Longhorn Helm chart version. Empty = latest; pin a tag (e.g. `1.7.2`) for reproducible installs.                                                                                                            |
| `longhorn_replica_count`         | `1`               | Default replicas per volume. Must be `<=` the number of nodes (asserted). `1` suits teaching/labs; raise to `3` (≥3 nodes) for production redundancy.                                                       |
| `longhorn_default_storage_class` | `true`            | Make Longhorn the default StorageClass. When `true`, k3s' built-in `local-path` storage is disabled (`--disable=local-storage`) so Longhorn is the only default.                                            |

### Bootstrap / client tooling

These tools (Helm, kubectl, Skaffold, shell aliases and completions) are installed on the **server node only** — agents have no kubeconfig, so they would be unusable there.

| Variable                         | Default  | Description                                                                                                      |
| -------------------------------- | -------- | ---------------------------------------------------------------------------------------------------------------- |
| `bootstrap_install_client_tools` | `true`   | Install Helm, kubectl, Skaffold and the shell aliases/completions on the server. Set to `false` for a lean node. |
| `helm_version`                   | `""`     | Helm version to install. Empty = latest stable; pin a tag (e.g. `v3.16.3`) for reproducible installs.            |
| `kubectl_version`                | `""`     | kubectl version to install. Empty = latest stable (`stable.txt`); pin a tag (e.g. `v1.31.4`).                    |
| `skaffold_version`               | `latest` | Skaffold release to install (`latest` or a tag such as `v2.13.2`).                                               |

### Cert-Manager

| Variable                                | Default                           | Description                                                                                                                                                                                                                  |
| --------------------------------------- | --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cert_manager_email`                    | `""`                              | ACME account email. Leave empty to skip cert-manager installation.                                                                                                                                                           |
| `cert_manager_url`                      | `https://certificates.dhbw.cloud` | ACME server URL.                                                                                                                                                                                                             |
| `cert_manager_namespace`                | `cert-manager`                    | Deployment namespace.                                                                                                                                                                                                        |
| `cert_manager_preferred_challenge`      | `dns01`                           | Challenge type: `dns01` or `http01`. `dns01` (default) needs the RFC2136 vars (see ExternalDNS) and uses the role-created TSIG secret; falls back to `http01` if they are unset.                                             |
| `cert_manager_rfc2136_tsig_secret_name` | `cert-manager-rfc2136-tsig`       | Name of the Secret the role creates (in the cert-manager namespace) holding the RFC2136 TSIG key for the `dns01` solver.                                                                                                     |
| `cert_manager_wildcard_secret_name`     | `wildcard-tls`                    | Name of the TLS Secret (in the Traefik namespace) holding the wildcard cert+key. When `dns01` is active the role issues a `*.<rfc2136_zone>` wildcard cert into this Secret and registers it as Traefik's default TLS store. |
| `cert_manager_cluster_issuer_name`      | `certificate-cluster-issuer`      | Name of the ClusterIssuer this role creates. Reference it from your Ingress/IngressRoute (e.g. the `cert-manager.io/cluster-issuer` annotation).                                                                             |
| `traefik_namespace`                     | `kube-system`                     | Namespace Traefik runs in (k3s bundles it in `kube-system`). The wildcard Secret and the default `TLSStore` are created here.                                                                                                |
| `cert_manager_private_key_secret_name`  | `cert-manager-private-key-secret` | Secret name for the ACME account private key (`privateKeySecretRef`).                                                                                                                                                        |
| `cert_manager_eab_keyid`                | `""`                              | External Account Binding Key ID (optional).                                                                                                                                                                                  |
| `cert_manager_eab_secret`               | `""`                              | External Account Binding MAC key (optional).                                                                                                                                                                                 |
| `cert_manager_eab_secret_name`          | `cert-manager-eab-secret`         | Secret name holding the EAB MAC key (only used when EAB is set).                                                                                                                                                             |

### ExternalDNS (RFC2136)

> **DHBW users:** register a DNS zone and generate the matching TSIG key (`rfc2136_zone`, `rfc2136_tsig_secret_value`, `rfc2136_tsig_secret_alg`, `rfc2136_tsig_secret_keyname`) at [self-service.dhbw.cloud](https://self-service.dhbw.cloud).

| Variable                           | Default                          | Description                                                                                                                         |
| ---------------------------------- | -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `rfc2136_zone`                     | _(unset)_                        | DNS zone. Leave unset to skip ExternalDNS installation.                                                                             |
| `rfc2136_dns_host`                 | `141.72.5.244`                   | RFC2136 DNS server IP (also the cert-manager `dns01` nameserver). Defaults to the DHBW DNS server; override for other environments. |
| `rfc2136_dns_port`                 | `53`                             | RFC2136 DNS server port.                                                                                                            |
| `rfc2136_tsig_secret_value`        | _(unset)_                        | TSIG secret value.                                                                                                                  |
| `rfc2136_tsig_secret_alg`          | _(unset)_                        | TSIG algorithm (e.g. `hmac-sha512`).                                                                                                |
| `rfc2136_tsig_secret_keyname`      | _(unset)_                        | TSIG key name.                                                                                                                      |
| `external_dns_namespace`           | `external-dns`                   | Namespace ExternalDNS is deployed into.                                                                                             |
| `external_dns_log_level`           | `debug`                          | ExternalDNS log level.                                                                                                              |
| `external_dns_txt_owner_id`        | `dynamic-zones-dns`              | Owner ID written into the registry TXT records. Make this unique per cluster when several clusters share a zone.                    |
| `external_dns_txt_prefix`          | `dynamic-zones-dns-`             | Prefix for the registry TXT records.                                                                                                |
| `external_dns_exclude_target_nets` | _(RFC1918/CGNAT/ULA/link-local)_ | CIDRs ExternalDNS must never publish (e.g. private/NAT addresses on a dual-stack node).                                             |
| `external_dns_version`             | `v0.19.0`                        | ExternalDNS Helm chart version.                                                                                                     |

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

---

## Changelog

This role uses calendar versioning (`YYYY.MM.DD`).

### 2026.06.04

**⚠️ Breaking — NGINX ingress removed; DNS-01 is now the default.** Update your inventory / `group_vars` / `host_vars`:

- Removed the optional NGINX ingress controller. The cluster always uses k3s' built-in **Traefik** — **remove `ingress_nginx_enabled`** from your variables.
- `cert_manager_preferred_challenge` now defaults to **`dns01`** (was `http01`). It still falls back to `http01` when the RFC2136 variables are unset.

**Added**
- **Automatic wildcard certificate.** When DNS-01 is active (zone + TSIG key set), the role issues a single `*.<rfc2136_zone>` certificate and registers it as Traefik's default TLS store, so every app under the zone is served over HTTPS without per-app certificate setup. Tunable via `cert_manager_wildcard_secret_name` and `traefik_namespace`.

**Removed**
- `ingress_nginx_enabled` and the NGINX install task / Helm repository.

**Changed**
- **Longhorn now defaults to auto:** enabled on a multi-node run, disabled on a single node (was always off). Override by setting `longhorn_enabled` explicitly.
- Task files renumbered after the NGINX removal (cert-manager `06`, ExternalDNS `07`, Longhorn `08`). No user-facing variables affected.
- README reorganized to lead with what the role provides (DNS + TLS) and how to expose an app; technical details moved further down.

### 2026.06.02

**⚠️ Breaking — variable renames.** Update your inventory / `group_vars` / `host_vars`:

| Old name                           | New name                           |
| ---------------------------------- | ---------------------------------- |
| `rfc2136_dns_tsig_secret_alg`      | `rfc2136_tsig_secret_alg`          |
| `rfc_2136_dns_host`                | `rfc2136_dns_host`                 |
| `rfc_2136_dns_port`                | `rfc2136_dns_port`                 |
| `external_dns_cluster_issuer_name` | `cert_manager_cluster_issuer_name` |

`rfc2136_zone`, `rfc2136_tsig_secret_value` and `rfc2136_tsig_secret_keyname` are unchanged. `rfc2136_dns_host` keeps its default of `141.72.5.244` (the DHBW DNS server) — only its name changed.

**Added**
- Optional **Longhorn** distributed block storage (`longhorn_enabled`, off by default) for replicated, node-independent volumes — recommended for multi-node clusters. Installs the iSCSI/NFS node prerequisites on all nodes; can become the default StorageClass (`longhorn_default_storage_class`). Aborts early if `longhorn_replica_count` exceeds the cluster node count. Default replica count is `1` (teaching-friendly; raise to `3` for production).
- Pinnable tool versions in bootstrap: `helm_version`, `kubectl_version`, `skaffold_version` (empty = latest, as before).
- `bootstrap_install_client_tools` to toggle Helm/kubectl/Skaffold + shell aliases/completions.
- Configurable ExternalDNS registry ownership: `external_dns_txt_owner_id`, `external_dns_txt_prefix`.

**Changed**
- Client/developer tooling (Helm, kubectl, Skaffold, aliases, completions) is now installed on the **server node only** — agents have no kubeconfig.
- Task files renumbered so the filename order matches the execution order (`00_network` → `03_network`; k3s install and add-ons shifted to `04`–`08`, Longhorn is `09`). No user-facing variables affected.
- README: documented previously undocumented variables, added a **Storage** section and this changelog; fixed the single-node example.

**Fixed**
- ExternalDNS: the Helm install now reads the rendered values file via the `external_dns_values_file` variable instead of a hardcoded path.
- Removed a misleading copy-paste comment in the ExternalDNS task and corrected the (mis-described) ClusterIssuer-name variable.
