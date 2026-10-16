# Hub-and-spoke network with Network Connectivity Center

![diagram](hub-and-spoke.png)

Built with `--mode legacy`: in a networking-heavy diagram, `modern` mode would draw Cloud Router,
Interconnect, Network Connectivity Center, PSC, Cloud NAT, Cloud Firewall and Cloud DNS with the same
*Networking* icon.

```bash
python3 scripts/gcp_drawio.py build examples/hub-and-spoke.src.drawio -o hub-and-spoke.drawio --mode legacy
```

## Topology

1. The corporate network reaches Google Cloud over **Cloud Interconnect** (2 VLAN attachments for
   redundancy). **Cloud Router** in `transit-vpc` exchanges routes with the on-premises routers over BGP.
2. A **Network Connectivity Center hub** in the `net-hub` project connects:
   - the VLAN attachments as a **hybrid spoke**;
   - `prod-vpc`, `data-vpc` and `dev-vpc` as **VPC spokes**.
3. NCC exchanges routes between all spokes. On-premises can reach every spoke, and spokes reach each
   other without VPC peering or appliances.
4. `data-prod` sits inside a **VPC Service Controls** perimeter. Its ETL workers reach BigQuery through
   a **Private Service Connect** endpoint for Google APIs, so data never leaves the perimeter over public
   endpoints.
5. `dev-vpc` reaches the internet through **Cloud NAT**. Its VMs have no external IP.

## Services

| Service | Where | Role |
|---|---|---|
| Cloud Interconnect | net-hub | Private link to the data center |
| Cloud Router | transit-vpc | BGP sessions over the VLAN attachments |
| Network Connectivity Center | net-hub | Hub: route exchange between all spokes |
| Cloud Firewall (hierarchical policies) | net-hub (applied at folder/org level) | Central firewall rules for every spoke |
| Cloud DNS | net-hub | Private zones shared with the spokes, forwarding to on-prem DNS |
| GKE, Cloud SQL | app-prod | Production workload, private IP database |
| Compute Engine, PSC endpoint, BigQuery | data-prod | ETL inside a VPC-SC perimeter |
| Compute Engine, Cloud NAT | app-dev | Dev VMs with NAT egress |

## Design decisions

- **NCC instead of VPC peering:** peering is not transitive. With a peered hub, spokes cannot reach each
  other or on-premises without network appliances. NCC VPC spokes provide full-mesh route exchange and
  include the hybrid routes.
- **NCC spokes are drawn as association edges** (dashed, no arrow): they are attachments, not hops.
  Traffic flows directly between the spoke VPCs and the VLAN attachments along the exchanged routes.
- **Separate projects per spoke** keep IAM, billing and quotas isolated. Shared network services stay
  in the hub project.
- **The perimeter wraps the project, not the VPC:** VPC Service Controls protects Google API access
  (BigQuery), not network traffic.
