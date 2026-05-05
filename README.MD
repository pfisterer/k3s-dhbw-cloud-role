# k3s-dhbw-cloud-role

Ansible Role for the installation and configuration of a production-ready K3s cluster, specifically optimized for the infrastructure requirements of the [DHBW Cloud](https://dhbw.cloud) (only accessible from the DHBW network).

This role automates the bootstrapping of Linux hosts and the deployment of essential cloud-native components:
- **K3s:** Lightweight Kubernetes distribution (server or agent mode).
- **NGINX Ingress Controller:** For external routing of traffic.
- **Cert-Manager:** For automated issuance and renewal of TLS certificates (ACME).
- **ExternalDNS:** For automatic management of DNS records (supports RFC2136/TSIG).

---

## Installation

Add the role to your requirements file (`requirements.yml`):

```yaml
---
- name: k3s-dhbw-cloud-role
  source: https://github.com/pfisterer/k3s-dhbw-cloud-role.git
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
      tags: [k3s]
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
          hosts:
            "141.72.5.244":
              ansible_user: root
              ip_family: ipv4
              cert_manager_email: your@mail.com
              # ... all other role variables ...

        production_k3s_agent:
          vars:
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
          hosts:
            "141.72.176.135":
              ansible_user: root
              ip_family: ipv4
              cert_manager_email: your@mail.com
              # ... all other role variables ...

        staging_k3s_agent:
          vars:
            k3s_server_host: "141.72.176.135"
          hosts:
            "141.72.176.201":
              ansible_user: root
```

**`playbook.yml`**
```yaml
---
# Play 1: install k3s server and all add-ons
- name: Deploy K3s servers
  hosts: "*_k3s_server"
  become: true
  roles:
    - role: k3s-dhbw-cloud-role

# Play 2: join worker nodes (token is read automatically from the server's hostvars)
- name: Join K3s agents
  hosts: "*_k3s_agent"
  become: true
  vars:
    k3s_role: agent
    k3s_token: "{{ hostvars[k3s_server_host]['k3s_node_token'] }}"
  roles:
    - role: k3s-dhbw-cloud-role
```

Run a single environment:

```bash
ansible-playbook playbook.yml -i inventory.yml --limit staging
ansible-playbook playbook.yml -i inventory.yml --limit production
```

---

## Variables

All variables are defined in `defaults/main.yml` and can be overridden per host or group.

### Node role

| Variable | Default | Description |
|---|---|---|
| `k3s_role` | `server` | Set to `agent` on worker nodes. |
| `k3s_server_host` | `""` | IP of the server to join. Required when `k3s_role: agent`. |
| `k3s_token` | `""` | Cluster join token. Pass via `hostvars` from the server play (see example above). |

### General

| Variable | Default | Description |
|---|---|---|
| `ip_family` | `ipv4` | IP version for TLS SANs and kubeconfig URL (`ipv4` or `ipv6`). |
| `k3s_exec_args` | `--disable=traefik --tls-san=<node_ip>` | Arguments passed to the k3s install script. |
| `kubeconfig_root` | `/etc/rancher/k3s/k3s.yaml` | Path to the kubeconfig on the server node. |

### Cert-Manager

| Variable | Default | Description |
|---|---|---|
| `cert_manager_email` | `""` | ACME account email. Leave empty to skip cert-manager installation. |
| `cert_manager_url` | `https://certificates.dhbw.cloud` | ACME server URL. |
| `cert_manager_namespace` | `cert-manager` | Deployment namespace. |
| `cert_manager_preferred_challenge` | `http01` | Challenge type: `http01` or `dns01`. |
| `cert_manager_eab_keyid` | `""` | External Account Binding Key ID (optional). |
| `cert_manager_eab_secret` | `""` | External Account Binding MAC key (optional). |

### ExternalDNS (RFC2136)

| Variable | Default | Description |
|---|---|---|
| `rfc2136_zone` | _(unset)_ | DNS zone. Leave unset to skip ExternalDNS installation. |
| `rfc_2136_dns_host` | `141.72.5.244` | RFC2136 DNS server IP. |
| `rfc_2136_dns_port` | `53` | RFC2136 DNS server port. |
| `rfc2136_tsig_secret_value` | _(unset)_ | TSIG secret value. |
| `rfc2136_dns_tsig_secret_alg` | _(unset)_ | TSIG algorithm (e.g. `hmac-sha512`). |
| `rfc2136_tsig_secret_keyname` | _(unset)_ | TSIG key name. |
| `external_dns_cluster_issuer_name` | `certificate-cluster-issuer` | Name of the ClusterIssuer to annotate ingresses with. |
| `external_dns_version` | `v0.19.0` | ExternalDNS Helm chart version. |

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
