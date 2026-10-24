# Development

Use Python 3.11+, Ruff and ShellCheck. Install the compatible Mesh Plus authority
package in the selected interpreter; see [configuration](configuration.md).

```sh
./scripts/check
```

The gate checks synthetic behavior, canonical Host Mesh fixtures, lint, format,
shell/text invariants and transfer provenance. It connects to no network host
and needs no active Rofi display. The wrapper and gate use commands from `PATH`;
select the intended Python/Ruff environment explicitly.

## Boundaries and layout

`rofi_ssh_plus/` owns picker behavior and the authority facade; `bin/` contains
the checkout wrapper. `contracts/host-mesh-v1/` is the canonical published bundle.
Consumers use the process contract, not private package/state imports.

`scripts/check-public-contract` supplies isolated public CLI probes.
`scripts/check-installed --self-test` checks callback/parser guards. Explicit
live checks have separate authorization/resource scopes; synthetic tests do
not establish SSH, graphical or installed fleet acceptance.

## Documentation

Keep current setup/behavior in [usage](usage.md), [configuration](configuration.md),
[design](DESIGN.md) and the [contract](HOST_MESH_V1.md). Completed plans and
performance notes belong under [history](history/README.md). Preserve canonical
bundle and evidence bytes; a navigation cleanup must not regenerate checksums
or rewrite old acceptance. The deployment owner retains managed pins and fleet
verification. Fleet Plus carries shared product presentation.
