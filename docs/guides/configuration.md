# Configuration and state

Mesh Plus is the default shared authority backend. Install the reviewed Mesh
package into the Python environment used by `bin/rofi-ssh-plus` (the checkout
wrapper invokes `python3` from `PATH`). A symlink alone installs no dependency.
See [Mesh setup](https://github.com/byebyebryan/mesh-plus/blob/main/docs/getting-started.md).

`ROFI_SSH_PLUS_MESH_BACKEND=mesh-plus` explicitly selects the default.
`ROFI_SSH_PLUS_MESH_BACKEND=legacy` selects the bundled standalone rollback
implementation. Missing/incompatible/unknown selected backends fail with typed
`invalid_config`; there is no automatic fallback. Selection applies to both the
picker and public mesh commands, without changing running services.

## Host catalog

The canonical [Host Mesh v1 guide](../reference/host-mesh-v1.md#configuration) defines the
TOML fields and examples. Use an explicit local logical identity and only peers
that this endpoint may reach. Directional routes grant no reverse membership.
SSH config, incoming connections, observed rows and history are not a registry.

Both backends preserve config, route-health paths, revision algorithm and lock.
Successful-connection history is separate and belongs to SSH Plus. A background
route-health report does not increase usage counts or recency.

## State and migration

The generic state file is:

```text
${XDG_STATE_HOME:-~/.local/state}/rofi-ssh-plus/history.json
```

It is a versioned JSON object containing `version`, `sortMode`, and `hosts`.
Each usage record has `host`, millisecond `lastConnected`, and positive `count`;
configured managed hosts with no usage record are rendered with zero count and
unknown age.
The parent directory is private (`0700`), the state and lock files are private
(`0600`), updates use an advisory lock and an atomic same-directory replace.

Schema version 1 retains `sortMode` for rollback compatibility, but its value is
not a user-visible setting. Missing, invalid, or legacy `frequency` values are
accepted and normalized to `recency` on the next write without resetting hosts,
timestamps, or counts. New writes always use `sortMode: "recency"`.

The optional strict Host Mesh configuration is:

```text
${XDG_CONFIG_HOME:-~/.config}/rofi-ssh-plus/config.toml
```

When present, it defines the local identity, configured logical hosts, ordered
routes, aliases, and SSH policy. A missing file safely synthesizes a local-only
mesh from the system hostname. Route health is kept separately at
`${XDG_STATE_HOME:-~/.local/state}/rofi-ssh-plus/route-health.json`; it never
changes usage counts or recency.

On the first read only, if the generic file does not exist, valid records are
imported from:

```text
${XDG_STATE_HOME:-~/.local/state}/DankMaterialShell/plugins/sshPlus_state.json
```

The legacy file is never modified or deleted. Invalid rows are skipped or
given safe defaults for missing count/timestamp fields; duplicate host
identity is merged case-insensitively (counts are added and the newest
timestamp wins). Even an absent or malformed legacy file creates an empty
generic state file, making the import one-time.

## Launch settings

`TERMINAL` selects a terminal command prefix parsed with `shlex.split`.
`ROFI_SSH_PLUS_CONNECT_TIMEOUT` is a positive probe timeout (default two seconds).
`ROFI_SSH_PLUS_SSH_COMMAND` selects one executable path, not extra SSH options.
The [usage guide](usage.md#reachability-and-process-ownership) explains argv,
probe classification, launch timing and history writes.
