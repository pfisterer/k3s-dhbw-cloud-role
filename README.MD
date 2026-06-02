# k3s-dhbw-cloud-role

Ansible Role for the installation and configuration of a production-ready K3s cluster, specifically optimized for the infrastructure requirements of the [DHBW Cloud](https://dhbw.cloud) (only accessible from the DHBW network).

This role automates the bootstrapping of Linux hosts and the deployment of essential cloud-native components:
- **K3s:** Lightweight Kubernetes distribution (server or agent mode).
- **CNI:** k3s' built-in flannel (plus kube-proxy and the network-policy controller) — the k3s defaults; works in IPv4, IPv6 and dual-stack on a single interface (see [CNI: flannel](#cni-flannel)).
- **NGINX Ingress Controller:** For external routing of traffic (optional, can be disabled in favour of the built-in Traefik).
- **Cert-Manager:** For automated issuance and renewal of TLS certificates (ACME).
- **ExternalDNS:** For automatic management of DNS records (supports RFC2136/TSIG).

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
      external_dns_cluster_issuer_name: cluster-issuer
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

### Cert-Manager

| Variable                           | Default                           | Description                                                        |
| ---------------------------------- | --------------------------------- | ------------------------------------------------------------------ |
| `cert_manager_email`               | `""`                              | ACME account email. Leave empty to skip cert-manager installation. |
| `cert_manager_url`                 | `https://certificates.dhbw.cloud` | ACME server URL.                                                   |
| `cert_manager_namespace`           | `cert-manager`                    | Deployment namespace.                                              |
| `cert_manager_preferred_challenge` | `http01`                          | Challenge type: `http01` or `dns01`. `dns01` needs the RFC2136 vars (see ExternalDNS) and uses the role-created TSIG secret; falls back to `http01` if they are unset. |
| `cert_manager_rfc2136_tsig_secret_name` | `cert-manager-rfc2136-tsig`  | Name of the Secret the role creates (in the cert-manager namespace) holding the RFC2136 TSIG key for the `dns01` solver.                                              |
| `cert_manager_eab_keyid`           | `""`                              | External Account Binding Key ID (optional).                        |
| `cert_manager_eab_secret`          | `""`                              | External Account Binding MAC key (optional).                       |

### ExternalDNS (RFC2136)

| Variable                           | Default                      | Description                                             |
| ---------------------------------- | ---------------------------- | ------------------------------------------------------- |
| `rfc2136_zone`                     | _(unset)_                    | DNS zone. Leave unset to skip ExternalDNS installation. |
| `rfc_2136_dns_host`                | `141.72.5.244`               | RFC2136 DNS server IP.                                  |
| `rfc_2136_dns_port`                | `53`                         | RFC2136 DNS server port.                                |
| `rfc2136_tsig_secret_value`        | _(unset)_                    | TSIG secret value.                                      |
| `rfc2136_dns_tsig_secret_alg`      | _(unset)_                    | TSIG algorithm (e.g. `hmac-sha512`).                    |
| `rfc2136_tsig_secret_keyname`      | _(unset)_                    | TSIG key name.                                          |
| `external_dns_cluster_issuer_name` | `certificate-cluster-issuer` | Name of the ClusterIssuer to annotate ingresses with.   |
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
