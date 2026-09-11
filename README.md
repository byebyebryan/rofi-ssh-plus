# rofi-ssh-plus

`rofi-ssh-plus` is a Rofi script-mode picker for SSH destinations that have
actually answered an SSH reachability check. It does not enumerate
`known_hosts` or SSH configuration, so the list stays small and useful. It also
provides the Host Mesh Contract v1 process boundary for logical hosts, route
candidates, and route health shared by the other suite pickers.

The current source implements the Host Mesh contract and the published,
deployed P8 flat-scope navigation. The published post-P9 recent-only SSH
refinement supersedes the original P8 Frequent/Recent lens without changing the
Host Mesh wire contract. Managed deployment and fleet acceptance are tracked by
the chezmoi repository. Its canonical P9 contract bundle is under
`contracts/host-mesh-v1/`. Consumers invoke
`rofi-ssh-plus mesh ... --json` through
`PATH`; they do not import this package or read its private state.
With an inherited Rofi `ROFI_RETV`, exactly one argv token `mesh` is treated as
the selected picker row. Any following token makes the invocation an explicit
Host Mesh CLI command, including invalid subcommands so they receive the
standard `invalid_input` envelope. Without `ROFI_RETV`, existing `mesh ...`
CLI behavior is unchanged.

## Requirements

- Python 3.11 or newer
- Rofi 2.0 or newer with script modes
- `ssh`
- A terminal accepting `-e`; `$TERMINAL` is used when set, otherwise `ghostty`

The runtime uses only Python's standard library. No third-party Python
packages, daemon, or compiled Rofi plugin is required.

## Install and invoke

Put an absolute symlink to `bin/rofi-ssh-plus` on `PATH`, or point Rofi at its
absolute checkout path. The symlink keeps the adjacent Python package
available to the thin wrapper. For example:

```sh
ln -s /absolute/path/to/rofi-ssh-plus/bin/rofi-ssh-plus \
  ~/.local/bin/rofi-ssh-plus
```

A direct invocation is:

```sh
rofi -show ssh-plus \
  -modes "ssh-plus:/absolute/path/to/rofi-ssh-plus/bin/rofi-ssh-plus" \
  -theme-str 'entry { placeholder: "Filter or type host · Enter connect · Ctrl+Enter new"; }' \
  -kb-cancel Escape,Control+g \
  -kb-accept-custom Control+Return \
  -eh 2
```

Create an absolute symlink to the checkout under the `ssh-plus` name in
`~/.config/rofi/scripts/`; Rofi then discovers that filename as the mode name:

```sh
ln -s /absolute/path/to/rofi-ssh-plus/bin/rofi-ssh-plus \
  ~/.config/rofi/scripts/ssh-plus
rofi -show ssh-plus \
  -theme-str 'entry { placeholder: "Filter or type host · Enter connect · Ctrl+Enter new"; }' \
  -kb-cancel Escape,Control+g \
  -kb-accept-custom Control+Return \
  -eh 2
```

The picker opens with configured logical hosts and recorded ad-hoc destinations
ordered strictly by most recent successful connection. Used destinations sort
by descending `lastConnected`; equal timestamps use deterministic host mesh
declaration/name tie-breakers and never use connection count. Never-used managed
hosts follow in Host Mesh declaration order. The prompt is simply `SSH`.
Connection count remains secondary metadata after relative age. Type a new
destination and press Ctrl+Enter to launch it; plain Enter selects the
highlighted row. An ad-hoc destination is added only after the detached worker
confirms that a server answered. A managed row tries its ordered routes and
records one logical-host usage after a route answers. The terminal opens even
when checks fail, so a password prompt or visible SSH error remains possible.

## Keys and actions

| Key/action | Behavior |
| --- | --- |
| Up/Down, Ctrl-P/Ctrl-N, Tab/Shift+Tab | Navigate rows using Rofi defaults |
| Left/Right | Move the filter cursor using Rofi defaults |
| Enter | Connect to the selected recorded host |
| Typed input + Ctrl+Enter | Probe and connect to a new destination |
| Shift+Delete | Remove the selected destination from history |
| Escape, Ctrl+G | Close the picker |

The selected row keeps its raw destination in Rofi's `info` and `meta` fields;
visible decoration never drives selection. Each row reserves two physical
lines: the destination is primary and the secondary line contains relative age
followed by connection count. SSH has no peer view, so Left/Right and
Ctrl+B/Ctrl+F retain Rofi's native filter-cursor behavior. Already-open P8
windows may still send callbacks 10, 11, or 12; they perform a recent-only
rerender without rewriting history merely to normalize `sortMode`, with
`keep-filter=true` preserving the query while resetting selection to the first
eligible row. Escape and Ctrl+G are explicitly
configured as native cancellation keys; Tab and Shift+Tab retain Rofi's normal
row navigation.

A hostname is compared case-insensitively and stored in its canonical lower-case
form. Connection counts are retained for metadata and migration but never
participate in ordering. Legacy, missing, or invalid `sortMode` is read as
recent-only and normalized on the next real write.

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

## Reachability and process ownership

For each connection the worker executes this argv, without a shell:

```text
ssh -o BatchMode=yes -o ConnectTimeout=2 <host> true
```

Exit 0 records the destination. A nonzero exit is also considered a reached
server when stderr contains `permission denied`, `host key verification`,
`remote host identification has changed`, or `userauth`, matching the DMS SSH
Plus behavior for password and host-key cases. DNS failures, refusal, route
failures, and timeouts are not recorded. The terminal is launched regardless
as an argv array (`$TERMINAL -e ssh <host>` or `ghostty -e ssh <host>`).

Contract consumers use the reached-host marker wrapper from
[Host Mesh Contract v1](docs/HOST_MESH_V1.md) for domain commands. A marker
proves that SSH authenticated and started the remote wrapper; a later domain
failure is not treated as a route failure.

Optional environment configuration is intentionally narrow:

- `TERMINAL` selects the terminal command prefix (parsed with `shlex.split`).
- `ROFI_SSH_PLUS_CONNECT_TIMEOUT` sets the positive probe timeout in seconds;
  the default is `2`.
- `ROFI_SSH_PLUS_SSH_COMMAND` selects one SSH executable path for probing and
  launch; it is passed as one argv element and does not accept extra options.

The picker starts a detached worker, and the worker starts the terminal in a
new session with standard input/output/error disconnected. For ad-hoc and
single-route managed hosts the terminal is started before the worker performs
the history probe, so Rofi can exit and the terminal can appear immediately.
Multi-route managed hosts remain probe-first so SSH Plus can select a reachable
fallback. History is still written only when the separate bounded probe
establishes that an SSH server answered.

## Limits and security choices

- History is capped at 100 records, dropping the lowest-ranked records when
  necessary.
- Input must be one nonempty token with no whitespace or control characters
  and must not begin with `-`; this blocks accidental SSH option injection.
- SSH argument passthrough, host editing/pinning, and config/known-hosts
  discovery remain intentionally out of scope. Declarative logical hosts and
  routes are supplied only by the Host Mesh configuration file.
- A successful reachability probe is not proof that authentication will
  complete in the interactive terminal. It only proves that the destination
  answered in a way consistent with a real SSH server.

Run `./scripts/check` for deterministic validation. It does not connect to
network hosts or require an active Rofi display session.
