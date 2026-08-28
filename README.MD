# k3s-dhbw-cloud-role

An Ansible role that turns one or more Linux hosts into a ready-to-use [k3s](https://k3s.io) Kubernetes cluster for the [DHBW Cloud](https://dhbw.cloud) (reachable from the DHBW network).

The point of the role is that the fiddly parts — **DNS** and **TLS** — are handled for you. Once it has run, every app you deploy automatically gets:

- **A public DNS name** — for any Ingress with a hostname under your zone, [ExternalDNS](https://kubernetes-sigs.github.io/external-dns/) creates the DNS record for you.
- **Valid HTTPS** — [cert-manager](https://cert-manager.io) obtains and auto-renews a TLS certificate (one wildcard `*.<your-zone>` by default), so your app is reachable over HTTPS with no per-app setup.

You also get a full k3s cluster (one server, optional worker nodes), the built-in **Traefik** ingress, IPv4 / IPv6 / dual-stack support, optional replicated storage ([Longhorn](https://longhorn.io)), and **automatic k3s upgrades** that keep the cluster current (rolling, in a nightly window — on by default, see [Automated upgrades](#automated-upgrades)).

To use it you only need to supply: the **host(s)** to install on, and — for certificates and DNS — an **email** and a **DNS zone**.

---

## TL;DR

You have a fresh Linux VM and want a Kubernetes cluster where every app automatically gets a DNS name and HTTPS. Here is the whole thing:

1. **Get your DNS zone + TSIG key** (DHBW: [self-service.dhbw.cloud](https://self-service.dhbw.cloud)).
2. **Install the role** on your machine straight from GitHub:
   ```bash
   ansible-galaxy install git+https://github.com/pfisterer/k3s-dhbw-cloud-role.git
   ```
   (or pin it via a `requirements.yml` — see [Installation](#installation)).
3. **Describe your host** in `inventory.yml` (IP, SSH user, email, zone + TSIG key) — see [Quickstart](#quickstart-single-node) below.
4. **Run it:**
   ```bash
   ansible-playbook playbook.yml -i inventory.yml
   ```
5. **Use the cluster:**
   ```bash
   export KUBECONFIG=./kubeconfig-<your-host>.yaml
   kubectl get nodes
   ```

That's it. Deploy an app with an `Ingress` whose host is under your zone, and DNS + HTTPS happen automatically — [see how](#exposing-an-app-with-dns--tls).

> **New to Ansible or Kubernetes?** Read [Before you start](#before-you-start) first — it lists what you need on your own machine and on the target host.

---

## Before you start

You run this role **from your own computer** (the "control node"); it configures a **remote host** (the VM that becomes the cluster) over SSH. You never install anything on the VM by hand.

**On your own machine you need:**

- **[Ansible](https://docs.ansible.com/ansible/latest/installation_guide/intro_installation.html)** (`ansible --version` should work). On macOS: `brew install ansible`; on Debian/Ubuntu: `sudo apt install ansible`.
- **An SSH key** that can log into the target host (`ssh <user>@<host>` should get you in without a password prompt).

**On the target host you need:**

- A fresh **Linux** server (Ubuntu/Debian work well) that you can reach over SSH.
- A user with **sudo/root** rights (the playbook uses `become: true`).
- Enough resources for k3s — see the official [k3s hardware requirements](https://docs.k3s.io/installation/requirements) (roughly 2 GB RAM / 2 vCPU as a baseline, plus whatever your workloads need).

**For automatic DNS + HTTPS you also need** (optional, but the whole point of the role):

- A **DNS zone** you control and a matching **TSIG key**. DHBW users register both at [self-service.dhbw.cloud](https://self-service.dhbw.cloud). Without them you still get a working cluster — just no automatic DNS/TLS.

New to the terms used here?

- **Control node** — your laptop, where you run `ansible-playbook`.
- **Ingress** — a Kubernetes object that says "expose this app under this hostname". This role turns that into real DNS + HTTPS automatically.
- **Zone** — the DNS domain your names live under, e.g. `your-name.dhbw.cloud`. Apps get names like `myapp.your-name.dhbw.cloud`.

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

### Quickstart (single node)

One host, full k3s server with all add-ons — the fastest way to get a working cluster.

**Step 1 — create two files** next to each other in an empty directory.

**`inventory.yml`** — describes *which* host to configure and *how*:
```yaml
all:
  hosts:
    "1.2.3.4":
      ansible_user: ubuntu
      cert_manager_email: your@mail.com

      # DNS + automatic (wildcard) TLS — set these to enable ExternalDNS and DNS-01.
      # Without them you still get a working cluster, just no automatic DNS/HTTPS.
      # DHBW: get your zone and TSIG key from https://self-service.dhbw.cloud
      rfc2136_zone: your-zone.example.com
      rfc2136_tsig_secret_value: "<TSIG key>"
      rfc2136_tsig_secret_alg: hmac-sha512
      rfc2136_tsig_secret_keyname: "<TSIG key name>"
```

**`playbook.yml`** — says *what* to do (apply this role to those hosts):
```yaml
---
- name: Deploy K3s
  hosts: all
  become: true
  roles:
    - role: k3s-dhbw-cloud-role
```

**Step 2 — run it:**
```bash
ansible-playbook playbook.yml -i inventory.yml
```

The run takes a few minutes (it installs k3s and all add-ons). When it finishes, a kubeconfig is written to your current directory as `./kubeconfig-<your-host>.yaml`.

**Step 3 — talk to your cluster:**
```bash
export KUBECONFIG=./kubeconfig-1.2.3.4.yaml
kubectl get nodes          # should show your node as "Ready"
```

That's a full cluster. Next, [expose an app](#exposing-an-app-with-dns--tls).

> **Tip:** re-running the playbook is safe — the role is idempotent, so you can run it again any time to apply changes or recover from a half-finished run.

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

The role works in IPv4-only, IPv6-only and dual-stack environments. **By default you don't configure this at all** — `ip_family` defaults to `auto`, which detects the stack from the host's addresses:

- both IPv4 and IPv6 present → **dual-stack** (the family you connect over becomes primary)
- only IPv6 → **IPv6-only**
- otherwise → **IPv4-only**

The externally reachable IP is likewise taken from the address Ansible connects through, so the common cases need no network settings.

**When to override it:** auto-detection sees *any* address of a family, including a private/NATed one. So on a host with public IPv6 and only a private IPv4 that you want to keep out of the cluster, set the family explicitly:

```yaml
"2001:db8::1":          # connect over the public IPv6 address
  ansible_user: root
  ip_family: ipv6       # force IPv6-only; ignore the private IPv4
  cert_manager_email: your@mail.com
```

The debug line `ip_family=auto → dual, primary=ipv4 ...` printed during the run shows what was detected — check it if the result is not what you expected. Valid values are `auto` (default), `ipv4`, `ipv6` and `dual`; for `dual`, `ip_family_primary` (`auto`/`ipv4`/`ipv6`) picks the primary family listed first in the CIDRs and `--node-ip`.

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

## Automated upgrades

The role keeps the cluster's k3s version current on its own. By default it deploys Rancher's [system-upgrade-controller](https://docs.k3s.io/upgrades/automated) plus two upgrade **Plans** (one for server, one for agent nodes). The controller cordons each node in turn, swaps the k3s binary via a privileged job and restarts the service — a controlled rolling upgrade instead of "all nodes at once". Server nodes are always upgraded before agents (the agent Plan waits for the server Plan to finish).

It is **enabled by default** (following the `stable` channel, inside the nightly maintenance window) and only deployed on the server node. Tune or disable it:

```yaml
k3s_auto_upgrade_enabled: true       # default; set false to opt out entirely
k3s_auto_upgrade_channel: "stable"   # follow a channel → auto-detects new releases ("always current")
# k3s_auto_upgrade_version: "v1.31.5+k3s1"  # …or pin one exact release (overrides the channel); bump it in Git
k3s_auto_upgrade_drain: true         # drain (evict pods) agent nodes before upgrading; false = cordon only
k3s_auto_upgrade_window_start: "02:00"  # only upgrade at night (see maintenance window below)
```

**Maintenance window.** By default upgrades only start inside a nightly window (`02:00`–`04:00` `Europe/Berlin`, every day) — the controller holds jobs until the window opens. This is the recommended setting when downtime is unavoidable (single node): the cluster reboots at 2 a.m., not mid-lecture. Widen or move it via `k3s_auto_upgrade_window_*`, or set `k3s_auto_upgrade_window_enabled: false` to upgrade as soon as a new release is detected, at any time.

**Channel vs. version.** `channel` mode follows a k3s release channel and upgrades automatically whenever a new release appears — the true "always up to date" behaviour, at the cost of unannounced version bumps. `version` mode pins one exact release you bump deliberately (reproducible; review each jump). A pinned `k3s_auto_upgrade_version` always overrides the channel. Never skip an intermediate minor version when pinning — k3s follows the Kubernetes version-skew policy and rejects such jumps (and downgrades).

> **Single node:** the upgrade cordons the one node, drains it (system pods restart) and swaps the binary in place, so there is a **short cluster downtime** during each upgrade — there is no second node to evacuate to. This is usually fine for a lab, but enable it as a conscious choice. On multi-node clusters workloads reschedule to the other nodes and only one node is unavailable at a time (`concurrency: 1`).

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
| `ip_family`             | `auto`                      | IP stack to configure: `auto` detects it from the host's default-route addresses (both → `dual`, only IPv6 → `ipv6`, else `ipv4`); or force `ipv4` / `ipv6` / `dual`. A private/NATed address still counts as "family present", so set it explicitly to exclude one. Drives TLS SANs, kubeconfig URL, `--node-ip` and the pod/service CIDRs. |
| `ip_family_primary`     | `auto`                      | Only used when `ip_family` resolves to `dual` — which family is **primary** (listed first in the CIDRs / `--node-ip`). `auto` uses the family Ansible connects over; or force `ipv4` (IPv6 as an add-on) / `ipv6` (e.g. only private/NATed IPv4 available). |
| `k3s_cluster_cidr_ipv4` | `10.42.0.0/16`              | IPv4 pod CIDR (k3s default).                                                                                                                                                                             |
| `k3s_service_cidr_ipv4` | `10.43.0.0/16`              | IPv4 service CIDR (k3s default).                                                                                                                                                                         |
| `k3s_cluster_cidr_ipv6` | `fd00:42::/56`              | IPv6 pod CIDR (ULA). Only applied when IPv6 is involved.                                                                                                                                                 |
| `k3s_service_cidr_ipv6` | `fd00:43::/112`             | IPv6 service CIDR (ULA). Only applied when IPv6 is involved.                                                                                                                                             |
| `upstream_dns_servers`  | `[]`                        | Upstream DNS resolvers for the node and — via CoreDNS' `forward . /etc/resolv.conf` — every pod. Empty = leave the host's resolver setup alone. A list writes `/etc/resolv.conf` statically (replacing a systemd-resolved symlink), keeps it immutable (`chattr +i`) against cloud-init/DHCP rewrites, and rolls CoreDNS on an existing cluster. At most three, bare IPv4/IPv6 literals. |
| `k3s_node_external_ip`  | `""`                        | Externally reachable node IP (`--node-external-ip`). Empty = auto-detect from the address Ansible connects through (`ansible_host`) whenever it differs from the internal interface address (e.g. NAT).  |
| `k3s_exec_args`         | `""`                        | Set to a non-empty string to **fully override** the dynamically computed k3s server install arguments. Empty = use the computed args.                                                                    |
| `k3s_extra_exec_args`   | `""`                        | Extra arguments appended verbatim to the computed k3s server install arguments.                                                                                                                          |
| `kubeconfig_root`       | `/etc/rancher/k3s/k3s.yaml` | Path to the kubeconfig on the server node.                                                                                                                                                               |
| `kubeconfig_path`       | `""`                        | Where the server's kubeconfig is fetched on the control node (path + filename). Empty = default `./kubeconfig-<inventory_host>.yaml`. Set to a fixed path to always write/overwrite the same file.       |

### Preflight (connectivity)

Before installing k3s, the role checks that the flannel overlay port is reachable between all nodes in **both directions** — see the [connectivity preflight note](#multi-node-server--agents) above for why this matters.

| Variable                       | Default | Description                                                                                                                                                                                            |
| ------------------------------ | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `preflight_connectivity_check` | _auto_  | Verify the flannel overlay port is reachable between all nodes in both directions before installing k3s. Auto: **on** for a multi-node run, **off** for a single node. Set `true`/`false` to override. |
| `preflight_overlay_port`       | `0`     | Overlay UDP port to probe. `0` = auto-detect: `8472` for the default VXLAN backend, `51820` when `wireguard` appears in `k3s_extra_exec_args`. Set a fixed port for other backends.                    |
| `preflight_probe_duration`     | `5`     | Seconds each node listens for probes from its peers. The default is comfortably longer than the senders need; raise it only on very slow links.                                                        |

### Storage (Longhorn)

| Variable                                        | Default           | Description                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| ----------------------------------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `longhorn_enabled`                              | _auto_            | Install Longhorn for replicated, node-independent volumes. Auto: **on** for a multi-node run, **off** for a single node. Set `true`/`false` to override. Installs the iSCSI/NFS prerequisites on all nodes.                                                                                                                                                                                                                                       |
| `longhorn_namespace`                            | `longhorn-system` | Namespace Longhorn is deployed into.                                                                                                                                                                                                                                                                                                                                                                                                              |
| `longhorn_version`                              | `""`              | Longhorn Helm chart version. Empty = latest; pin a tag (e.g. `1.7.2`) for reproducible installs.                                                                                                                                                                                                                                                                                                                                                  |
| `longhorn_replica_count`                        | `1`               | Default replicas per volume. Must be `<=` the number of nodes (asserted). `1` keeps disk at 1× (each replica is a full copy; `2` doubles, `3` triples the footprint) and still upgrades cleanly thanks to `longhorn_node_drain_policy`. Raise to `2`/`3` only for redundancy against a node **failure** (storage-vs-resilience trade-off, independent of upgrades). |
| `longhorn_replica_auto_balance`                 | `least-effort`    | Longhorn `replica-auto-balance`: rebalance replicas across nodes when scheduling allows (e.g. after a drained node rejoins). `least-effort` / `best-effort` / `disabled`.                                                                                                                                                                                                                                                                          |
| `longhorn_data_locality`                        | `best-effort`     | Longhorn `default-data-locality`, applied both to the `longhorn` StorageClass and as the global default. `best-effort` keeps a replica on the node the volume is attached to so normal I/O never crosses the pod network — the value the Longhorn best practices recommend. `disabled` is the chart default; `strict-local` pins the single replica to the workload's node and is only for self-replicating applications. Applies to new volumes; existing ones keep the locality in their spec. |
| `longhorn_node_drain_policy`                    | `block-for-eviction-if-contains-last-replica` | Longhorn `node-drain-policy`. The eviction default live-migrates the last replica off a node before allowing the drain, so the automatic k3s upgrades never hang — even for single-replica volumes. The Longhorn chart default (`block-if-contains-last-replica`) blocks the drain indefinitely; `always-allow` risks unavailability during drains. |
| `longhorn_default_storage_class`                | `true`            | Make Longhorn the default StorageClass. When `true`, k3s' built-in `local-path` storage is disabled (`--disable=local-storage`) so Longhorn is the only default.                                                                                                                                                                                                                                                                                  |
| `longhorn_storage_over_provisioning_percentage` | `300`             | How much storage Longhorn may reserve across all volumes, as a percentage of each node's disk. Longhorn reserves by requested PVC size, not bytes written, and volumes are thin-provisioned, so the total can safely exceed the physical disk. The chart default (`100`) is tight on the small lab VMs and makes storage-hungry workloads (e.g. the Apache Ozone lab) fail to schedule replicas. The default `300` gives generous headroom; lower it (e.g. `100`) to be conservative on nodes with larger disks. |
| `longhorn_orphan_resource_auto_deletion`        | `replica-data;instance` | Longhorn `orphan-resource-auto-deletion`: which orphaned resources Longhorn garbage-collects by itself. `replica-data` = replica directories no longer tracked by any volume, `instance` = engine/replica runtime instances left behind when an instance-manager dies (the stale entries that make a later attach fail with "connection refused"). Empty — the chart default — means orphans accumulate until removed by hand. The Helm key for this changed name between chart versions and unknown `defaultSettings` keys are silently ignored, so pin `longhorn_version`. |
| `longhorn_orphan_resource_auto_deletion_grace_period` | `300`       | Seconds before an orphaned resource is deleted, so a merely-rebooting node has time to reclaim its replicas. Longhorn's own default, kept explicit as the safety margin on the setting above. |

### Automated upgrades (system-upgrade-controller)

Deployed on the **server node only**, and only when `k3s_auto_upgrade_enabled` is `true` (the default). See [Automated upgrades](#automated-upgrades) above.

| Variable                            | Default          | Description                                                                                                                                    |
| ----------------------------------- | ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `k3s_auto_upgrade_enabled`          | `true`           | Deploy the system-upgrade-controller + server/agent upgrade Plans to keep k3s current. **On by default** (follows `stable`, nightly window); means self-driven version changes and brief node cordoning per upgrade. Set `false` to opt out. |
| `k3s_auto_upgrade_channel`          | `stable`         | Release channel the Plans follow (turned into `https://update.k3s.io/v1-release/channels/<channel>`). Auto-detects new releases.              |
| `k3s_auto_upgrade_version`          | `""`             | Pin one exact release (e.g. `v1.31.5+k3s1`). Non-empty overrides the channel. Never skip an intermediate minor version.                       |
| `k3s_auto_upgrade_drain`            | `true`           | Drain (force-evict pods) agent nodes before upgrading; `false` = cordon only. Server nodes are always cordon-only.                            |
| `k3s_auto_upgrade_window_enabled`   | `true`           | Only start upgrade jobs inside the maintenance window below. `false` = upgrade whenever a new release is detected. Recommended `true` when downtime is unavoidable (single node). |
| `k3s_auto_upgrade_window_days`      | _(all 7 days)_   | Lowercase weekday names the window is active on. Trim (e.g. weekends only) to space out upgrades.                                             |
| `k3s_auto_upgrade_window_start`     | `02:00`          | Window start, `HH:MM` in `k3s_auto_upgrade_window_timezone`.                                                                                  |
| `k3s_auto_upgrade_window_end`       | `04:00`          | Window end, `HH:MM`. Keep it long enough for an upgrade to start.                                                                             |
| `k3s_auto_upgrade_window_timezone`  | `Europe/Berlin`  | IANA timezone the window times are interpreted in.                                                                                            |
| `system_upgrade_namespace`          | `system-upgrade` | Namespace the controller and Plans live in.                                                                                                   |
| `system_upgrade_controller_version` | `latest`         | system-upgrade-controller release to install. `latest` tracks the newest GitHub release; pin a tag (e.g. `v0.16.0`) for reproducibility.       |

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
| `cert_manager_wildcard_secret_name`     | `wildcard-tls`                    | Name of the TLS Secret (in the Traefik namespace) holding the wildcard cert+key, and of the `Certificate` requesting it.                                                                                                      |
| `cert_manager_wildcard_zone`            | `rfc2136_zone` while `dns01` is active, else `""` | Zone for the primary `*.<zone>` SAN, and the opt-in for the wildcard: empty means none is requested. Set it explicitly to get a wildcard **without** `dns01` — which only works where the CA issues one without a challenge because the domains are pre-validated on the ACME account. Over `http01` a wildcard cannot be validated and the Order retries forever. Deliberately separate from `rfc2136_zone`, which also gates the ExternalDNS installation. |
| `cert_manager_wildcard_additional_dns_names` | `[]`                         | Further SANs on the same certificate, written out in full (e.g. `"*.apps.example.com"`) — for a deployment spanning more than one zone.                                                                                       |
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
| `external_dns_version`             | `v0.21.0`                        | ExternalDNS container image tag. Keep at `v0.21.0` or newer: older versions crash-loop on transient AXFR failures.                  |
| `external_dns_chart_version`       | `1.21.1`                         | ExternalDNS Helm chart version. Empty = latest; keep in sync with the image tag above.                                               |
| `external_dns_interval`            | `5m`                             | Reconciliation interval. Each run is a full AXFR of the zone, so raising this reduces load on the shared RFC2136 server.             |
| `external_dns_trigger_loop_on_event` | `true`                         | Reconcile on Ingress/IngressRoute events (`--events`), so a longer interval does not delay new records.                              |

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

### 2026.08.28

**Added**
- **`upstream_dns_servers`** (default `[]`) — the node's upstream resolvers, written to `/etc/resolv.conf` as a static, immutable file (a systemd-resolved symlink is replaced, `chattr +i` keeps cloud-init and DHCP hooks from rewriting it) and rolled into CoreDNS on an already-installed cluster. Empty leaves the host alone, so existing setups are unchanged. Cloud images ship a single DHCP-supplied or hand-edited resolver, and CoreDNS (`forward . /etc/resolv.conf`) can only fail over between resolvers it can see; on 2026-08-27 the path to that one resolver flapped for nine hours and took every external-name lookup on the cluster with it. Tag `upstream_dns`.

### 2026.08.17

**Fixed**
- **The role's tags now reach the tasks they name.** `tasks/main.yml` uses dynamic includes, which do not pass their tags to the tasks they pull in — so a run like `--tags certmanager` (or `longhorn`, `externaldns`, `bootstrap`, …) matched the include, read the file, and then skipped every task inside it. It reported success and did nothing, which is the worst way for this to fail. Every include now carries `apply: tags:` in addition to its own tags. If you have been relying on a full run or `--tags k3s` because a narrower tag "did not work", that is why.

**Changed**
- **The wildcard certificate is no longer welded to DNS-01.** It is now requested whenever `cert_manager_wildcard_zone` names a zone; that variable defaults to `rfc2136_zone` while DNS-01 is active, so **nothing changes for existing DNS-01 users**. What it adds is the case the role previously could not serve: a CA that issues a wildcard without a running challenge because the domains are pre-validated on the ACME account (an organisation account with EAB typically is). Note the limit this does not lift — over `http01` a wildcard is not validatable, and forcing one creates an Order that retries forever.
- A separate variable rather than reusing `rfc2136_zone`, because that one is also the sole gate for the ExternalDNS installation: setting it just to obtain a certificate would deploy a DNS controller as a side effect.

**Added**
- **`cert_manager_wildcard_additional_dns_names`** (default `[]`) — further SANs on the same certificate, written out in full, for a deployment that spans more than one zone (e.g. `*.example.com` plus `*.apps.example.com`). The primary `*.<zone>` SAN stays first, so an existing certificate is not reissued.

### 2026.07.04

**Added**
- **Longhorn drain/rebalance settings so the automatic k3s upgrades never hang on single-replica volumes.** New `longhorn_node_drain_policy` (default `block-for-eviction-if-contains-last-replica`) makes Longhorn live-migrate the last healthy replica off a node before allowing the rolling upgrade to drain it — the chart default `block-if-contains-last-replica` would block the drain indefinitely (`DeadlineExceeded` → node stuck cordoned). New `longhorn_replica_auto_balance` (default `least-effort`) rebalances replicas across nodes when scheduling allows (e.g. after a drained node rejoins). This keeps `longhorn_replica_count: 1` (1× disk usage) safe for upgrades without a permanent second copy; raising the replica count is now only about redundancy against a node *failure*.

**Fixed**
- **k3s kernel sysctls are now idempotent.** The `ansible.posix.sysctl` module falsely reported `changed` on every run for the `net.netfilter.*` keys even when file and runtime values already matched. The tuning is now written as a single `/etc/sysctl.d/99-k3s.conf` file and reloaded (`sysctl --system`) only when the file content actually changes.

### 2026.07.01

**Added**
- **Automatic k3s upgrades via Rancher's [system-upgrade-controller](https://docs.k3s.io/upgrades/automated) — on by default (`k3s_auto_upgrade_enabled`).** The server node deploys the controller plus two upgrade Plans (server + agent); the controller cordons each node in turn, swaps the k3s binary and restarts the service — a controlled rolling upgrade, servers before agents (`concurrency: 1`). Track a release channel (`k3s_auto_upgrade_channel`, default `stable` → auto-detects new releases) or pin one exact release (`k3s_auto_upgrade_version`, overrides the channel). Agent nodes drain by default (`k3s_auto_upgrade_drain`); servers are always cordon-only. Upgrades run only inside a nightly maintenance window (`k3s_auto_upgrade_window_*`, default `02:00`–`04:00` `Europe/Berlin`) so the unavoidable brief downtime on a single node lands at night; disable the window (`k3s_auto_upgrade_window_enabled: false`) to upgrade immediately. Set `k3s_auto_upgrade_enabled: false` to opt out. Verified end-to-end on a 3-node cluster (v1.35.6 → v1.36.2).

**Fixed**
- **`kubernetes` Python client is now installed via pip (`>=24.2.0`) instead of apt.** The `python3-kubernetes` apt package on Ubuntu is capped at ~22.x, which made the `kubernetes.core` collection warn `kubernetes<24.2.0 is not supported or tested`. The server node now installs a current client with pip (using the module's `break_system_packages` for PEP 668), so the warning is gone and the client stays on a supported version.

**Changed**
- **`ip_family` now defaults to `auto` and is detected from the host** (was hardcoded `ipv4`). Auto-detection reads the interface default-route addresses: both families present → `dual`, only IPv6 → `ipv6`, otherwise `ipv4`; `ip_family_primary` also defaults to `auto` (the family Ansible connects over). A resolved-family `debug` line is printed during the run. Explicit `ipv4`/`ipv6`/`dual` values keep working unchanged.
  - **Mildly breaking:** a host that omitted `ip_family` and happens to have an IPv6 default route in addition to IPv4 is now configured as **dual-stack** instead of IPv4-only. Auto-detection also counts a **private/NATed** address as "family present" — set `ip_family` explicitly to force a single family on such hosts. Pin `ip_family: ipv4` (and `ip_family_primary: ipv4`) to keep the previous behaviour exactly.

**Documentation**
- README reworked for first-time users: added a **TL;DR** and a **Before you start** (prerequisites + glossary) section, turned the single-node example into a step-by-step **Quickstart**, linked the official [k3s hardware requirements](https://docs.k3s.io/installation/requirements) instead of hardcoding values, and simplified the IPv6/dual-stack section around the new auto-detection.

### 2026.06.24

**Added**
- **Configurable Longhorn over-provisioning (`longhorn_storage_over_provisioning_percentage`, default `300`).** Sets Longhorn's `storageOverProvisioningPercentage` (in `tasks/08_addons_longhorn.yml`). Longhorn reserves disk by requested PVC size (not bytes written) and its volumes are thin-provisioned, so the reserved total can safely exceed the physical disk. The chart default of `100` is tight on the small lab VMs and made storage-hungry workloads (notably the Apache Ozone lab, which requests several volumes) fail to schedule replicas with "insufficient storage". The default of `300` gives generous headroom; the 25%-minimal-available guard still prevents a disk from actually filling. Lower it (e.g. `100`) to be conservative on nodes with larger disks.

### 2026.06.11

**Added**
- **Inter-node connectivity preflight.** On multi-node runs the role now verifies — before installing k3s — that the flannel overlay port (VXLAN **UDP 8472** by default) is reachable between every pair of nodes in **both directions**, using a small dependency-free UDP probe against a cooperative listener on each node. This catches the common OpenStack case where the security group allows TCP/ICMP but drops the VXLAN UDP port, which otherwise forms a healthy-looking cluster that silently black-holes cross-node pod traffic. Auto-enabled for multi-node clusters; tune via `preflight_connectivity_check`, `preflight_overlay_port` and `preflight_probe_duration`.

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
