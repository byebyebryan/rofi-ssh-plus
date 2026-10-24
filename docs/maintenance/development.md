# Development

Use Python 3.11+, Ruff and ShellCheck. Install the compatible Mesh Plus authority
package in the selected interpreter; see [configuration](../guides/configuration.md).

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

## Documentation maintenance

Keep only `README.md` and `getting-started.md` at the docs root. Use lowercase
kebab-case filenames in one shallow topic folder: `guides/` for workflows,
`reference/` for current interfaces, and `maintenance/` for development/operations.
Media belongs in `assets/`. Mesh's hash-locked `contract-freeze.md` is the sole
root exception; its original bytes remain normative input.

Update or consolidate the existing guide instead of adding a dated plan,
handoff or status page. Delete superseded notes; Git retains earlier revisions.
Do not add forwarding pages or copy old reports into the current docs tree.
Keep executable test data beside tests, not under docs. Record necessary release
provenance with an immutable Git/release link in the operations guide.

Run `scripts/check-docs` and the canonical source gate before committing. The
docs check enforces this layout and checks local links/heading fragments.
Package, native, managed, consumer and physical acceptance remain separate.
