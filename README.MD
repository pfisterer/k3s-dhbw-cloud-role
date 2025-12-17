# 🚀 k3s-dhbw-cloud-role

Ansible Role for the installation and configuration of a production-ready K3s cluster, specifically optimized for the infrastructure requirements of the [DHBW Cloud](https://dhbw.cloud) (only accessible from the DHBW network).

This role automates the bootstrapping of Linux hosts and the deployment of essential cloud-native components:
- **K3s Server:** Lightweight Kubernetes distribution.
- **NGINX Ingress Controller:** For external routing of traffic.
- **Cert-Manager:** For automated issuance and renewal of TLS certificates (ACME).
- **ExternalDNS:** For automatic management of DNS records (supports RFC2136/TSIG).

---
## Installation and Usage

### Prerequisites

- One or more Linux hosts (Ubuntu/Debian) with SSH access.
- Ansible installed on the control node.


### Integrating the Role

Add the role to the requirements file (`requirements.yml`):

```yaml
---
- name: k3s-dhbw-cloud-role
  source: https://github.com/pfisterer/k3s-dhbw-cloud-role.git
  # Optional: Specify a tag, branch, or commit hash. 
  # If omitted, 'master' or 'main' branch is used by default.
  # version: main 
  # version: v1.0.0 # Example for a specific release tag
```

Then run `ansible-galaxy install -r requirements.yml` to install the role.

### Customization

All variables are defined in `defaults/main.yml`. These values represent the base configuration and can be overridden in your inventory or playbook.

Example inventory file (`inventory.yml`):

```yaml
all:
    hosts:
        "141.1.2.3":
            ip_family: ipv4
            ansible_user: ubuntu
            kubeconfig_path: /etc/rancher/k3s/k3s.yaml

            cert_manager_email: your@mail.com
            external_dns_cluster_issuer_name: cluster-issuer
```

### Playbook Example

```yaml
---
- name: Deploy K3s Cluster
  hosts: all
  become: yes
  roles:
    - role: k3s-dhbw-cloud-role 
      tags: [k3s]
```

### Accessing the Kubernetes Cluster

Upon successful execution, the cluster's Kubeconfig file will be fetched to the Ansible control node in the file `./kubeconfig-<hostname>.yaml`.

