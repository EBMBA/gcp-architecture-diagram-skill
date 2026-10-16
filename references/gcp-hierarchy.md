# Google Cloud boundaries: what goes inside what

Getting boundaries wrong is the most common mistake in GCP diagrams, usually by copying AWS habits
(VPC inside a region, everything inside the VPC). Use this page to decide nesting.

## Resource hierarchy (governance)

```
Organization ─┬─ Folder ─┬─ Project ── resources
              │          └─ Project
              └─ Project
```

- Draw `organization` and `folder` only when the diagram is about governance, landing zones, IAM or
  billing. For an application architecture, the outermost box is usually `google_cloud` with one or more
  `project` boxes inside.
- Several projects (prod/dev, host/service project for Shared VPC, data platform vs. apps): one
  `project` box each, side by side.

## Network (where resources live)

| Scope | Examples | Draw as |
|---|---|---|
| **Global** | VPC network, firewall rules, routes, global external Application Load Balancer, Cloud CDN, Cloud Armor, Cloud DNS, IAM | `vpc` box spanning regions; global edge services *outside* any region, on the left |
| **Regional** | Subnets, Cloud Run, Cloud Functions, regional GKE, Cloud SQL (with HA in 2 zones), Memorystore, Pub/Sub topics (global API, regional storage), Cloud NAT, Cloud Router, internal LB | `region` box; subnets inside it |
| **Zonal** | Compute Engine VMs, zonal GKE node pools, Persistent Disk, Filestore basic | `zone` box inside a subnet, only when zones matter (HA, failover) |
| **Multi-region / global managed** | Cloud Storage (multi-region), BigQuery datasets (US/EU), Spanner multi-region, Firestore | in the `project`, outside the VPC |

## Nesting rules

1. `google_cloud` ⊃ `project` ⊃ `vpc`. A VPC belongs to exactly one project (Shared VPC: the *host*
   project).
2. **A VPC is global.** Inside the VPC, draw one `region` box per region, then `subnet` boxes inside the
   region. Never draw a VPC inside a region box.
   - Simplification allowed for single-region diagrams: `vpc` ⊃ `subnet` directly, with the region in the
     subnet label (`subnet-app · europe-west1 · 10.10.0.0/24`).
3. **Serverless and managed services are not in your VPC**: Cloud Run, Cloud Functions, App Engine,
   Pub/Sub, BigQuery, Cloud Storage, Firestore, Vertex AI, Dataflow (workers can run in a subnet: put
   the Dataflow node in the subnet only if the diagram is about its networking).
   Place them in the `project` box (optionally in a `region` box *outside* the VPC).
4. **Private-IP managed services** (Cloud SQL private IP, Memorystore, AlloyDB, Filestore) live in a
   Google-managed *producer* VPC peered to yours. Usual depiction: inside your `vpc` box near the subnet
   that consumes them, label "private IP". For a networking-focused diagram, draw a separate
   `logical` box "Google-managed services VPC" connected through Private Service Access.
5. GKE: `cluster` box inside the subnet (regional cluster: spans zones; draw `zone` boxes inside it only
   to show node distribution). Workloads (Deployments / Services) inside the cluster box use
   `gcpIcon=category:containers`, labeled with the workload name. Use `gcpIcon=gke` only for the
   cluster itself, when it is drawn as a single icon instead of a box.
6. Load balancers: the global external Application LB sits at the edge, **outside the VPC**, between
   users and backends. Internal LBs sit inside the subnet of their frontend IP.
7. VPC Service Controls: `vpc_sc` perimeter around the *projects / services* it protects (often
   BigQuery, Cloud Storage), not around the VPC.
8. Hybrid: `on_premises` box on the far right (or left). Never straddle a border with an icon (its label
   would sit on the border):
   - Cloud Interconnect / Cloud VPN: inside the `project`, **outside the `vpc`**, in the gap between the
     VPC and the `on_premises` box (it is a project resource attached to the VPC).
   - Cloud Router: inside the `vpc` (regional), in a lane **above or below** the data path, not on it.
   - Data path: workload → Interconnect/VPN → on-prem system, as normal edges. Cloud Router connects to
     the Interconnect/VPN with an association edge (`dashed=1;endArrow=none;`, label `BGP`): it exchanges
     routes, it does not carry traffic.

## Connections into the VPC

| From | To | Draw |
|---|---|---|
| Cloud Run / Functions | resource in VPC | edge labeled `Direct VPC egress` or `VPC connector` into the subnet |
| Your VPC | Google APIs privately | edge labeled `Private Google Access` or a `private_service_connect` icon |
| Consumer VPC | producer service | `private_service_connect` icon on the consumer side |
| VMs without external IP | internet | `cloud_nat` + `cloud_router` icons in the region, edge to `gcpShape=internet` |

## Typical outer layout (left to right)

```
[users/clients] → [edge: DNS, LB, CDN, Armor] → [project: compute → data] → [external systems]
                                                [ops lane below: Logging, Monitoring, Secret Manager]
```
