# SSH Plus documentation

Start with the [repository README](../README.md) for requirements, installation,
configuration and picker interaction. The [product walkthrough](https://dev.byebyebryan.com/fleet-plus/projects/ssh-plus/)
and [Fleet Plus architecture](https://dev.byebyebryan.com/fleet-plus/architecture/)
provide shared orientation.

| Guide | Scope |
| --- | --- |
| [Host Mesh v1](HOST_MESH_V1.md) | Supported public process interface and canonical contract ownership |
| [Picker design](DESIGN.md) | Navigation, SSH actions and historical design checkpoints |
| [Startup performance](mesh-startup-performance.md) | Dated bounded startup measurements and implementation decisions |
| [Canonical wire contract](../contracts/host-mesh-v1/contract.md) | Exact Host Mesh v1 envelopes and semantics |

Mesh implements host/route authority; SSH Plus owns its public facade, connection
history and picker UX. Consumers use the public process contract. Configured
membership is endpoint-specific and directional; a successful connection does
not authorize reverse host discovery or delivery.

Installed authority versions are independently selected by the deployment owner.
Dated evidence retains its original source/artifact/host scope.
