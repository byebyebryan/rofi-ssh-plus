# Host Mesh v1 producer fixtures

These fixtures are deliberately synthetic and contain no private machine,
route, or username data. They are producer-owned examples for consumers to
copy into their own conformance tests; consumers must not import
`rofi_ssh_plus` or read the private state files.

`config-local-only.toml` covers the no-configuration fallback and
`config-multi-route.toml` is the canonical configured mesh. The JSON fixtures
describe deterministic health-report, marker, migration, and envelope cases.
Timestamps use an artificial Unix-millisecond clock so tests do not depend on
wall time.
