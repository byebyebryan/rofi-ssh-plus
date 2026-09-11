# Design: rofi-ssh-plus

Status: the picker, successful-connection history, and Host Mesh v1 provider
are implemented, deployed, and accepted as part of P6 suite integration.
P7 removes the synchronous terminal-launch gate for ad-hoc destinations
and managed hosts with one route while preserving probe-first selection for
multi-route fallback. The coordinated P8 flat-scope navigation cutover is
published and deployed, with operator acceptance complete on Snap and
Starship; Carbon is in a daily-drive soak. The P9 producer implementation and
canonical bundle are published in this repository; managed suite deployment is
coordinated through chezmoi while the Host Mesh v1 wire behavior stays
compatible. The published post-P9 recent-only SSH refinement supersedes the
original P8 Frequent/Recent lens, restores native Left/Right filter editing,
and leaves the P9 wire contract unchanged. Chezmoi owns managed deployment and
fleet/operator acceptance status.

## P8 navigation and post-P9 SSH refinement

P8 made SSH Plus structurally flat: hosts are leaf rows and there is no peer
view, while retaining its existing Frequent/Recent ordering lens. The
post-P9 refinement below supersedes only that SSH lens and ordering choice.

### Post-P9 recent-only SSH refinement

SSH Plus now has one recent-only view. Hosts are leaf rows and there is no peer
view.

Successful destinations are ordered by `lastConnected` descending; count is
metadata only and never a ranking key. Equal timestamps use deterministic
Host Mesh declaration/name tie-breakers, while never-used managed hosts remain
in declaration order after all used rows. Left and Right therefore retain
Rofi's native filter-cursor actions instead of switching a meaningless view.

Tab and Shift+Tab remain Rofi-native row navigation; Enter connects to the
selected host; and Escape plus Ctrl+G remain entirely on Rofi's native cancel
path. Neither cancellation key is a script callback. Already-open P8 windows
may still send callbacks 10, 11, or 12; these render the same recent-only rows,
preserve the filter, and do not rewrite history merely to normalize
`sortMode`, probe routes, launch a terminal, or capture cancellation.

The original P8 cutover did not change successful-connection history, custom
input, route selection, or Host Mesh v1. P9 itself did not change picker
behavior; this subsequent refinement changes only SSH presentation/state
ordering and leaves the P9 wire contracts unchanged.

## P9 locked CLI contracts

P9 keeps Host Mesh as a local executable contract and makes its current v1
wire format machine-verifiable. SSH Plus owns the complete canonical bundle:
Draft 2020-12 JSON Schemas, machine metadata, normative semantic rules,
checksums, and synthetic valid plus raw-invalid fixtures for `mesh list` and
`mesh report-route`. Producer tests will validate actual success and error
documents against those artifacts.

The v1 runtime protocol does not gain a discovery command, package import, or
second discriminator. The invoked command and existing `schemaVersion` remain
the identity. Stdout is one strict UTF-8 JSON document followed by exactly one
LF, stderr is bounded human diagnostics, and only a matching typed JSON
error/nonzero-exit pair can authorize contract behavior. Numeric nonzero exit
codes and stderr text are not semantic APIs.

Tmux Plus and Agent Plus continue to validate Host Mesh independently. They
vendor the complete small contract bundle with one exact `SOURCE.json`
provenance record for offline conformance tests, but they do not import this
package or read its configuration and state. A command that does not resolve
through `PATH` remains the only local-only fallback; once a path resolves, a
launch failure, timeout, overflow, malformed document, or unsupported schema
remains a visible failure.

P9 does not alter route order, Mesh revision, report monotonicity, reached-host
markers, SSH history, or picker behavior. The coordinated suite design and
rollout boundary live in the managed `rofi-plus-p9-cli-contracts.md` document.

## Product boundary

This project replaces the DMS SSH Plus presentation layer with a Rofi
script-mode picker. It keeps the useful product rule from DMS SSH Plus:
history contains only destinations for which the pre-flight probe established
that an SSH server answered. The picker never scans `~/.ssh/known_hosts` or
`~/.ssh/config`; successful use is the source of truth.

The current source owns successful-destination history and implements the
[Host Mesh Contract v1](HOST_MESH_V1.md), extending that ownership to logical
host IDs, aliases, ordered routes, and route health for `rofi-tmux-plus` and
`rofi-agent-plus`. The contract deliberately separates background route-health
observations from explicit user connections so suite consumers cannot distort
SSH recency.

The mesh-aware picker has one recent-only ordering. It retains the v1
`sortMode` field for rollback-compatible state reads and treats every missing,
invalid, or legacy `frequency` value as `recency` without rewriting state until
the next real mutation. History is never reset.
Configured remote hosts are always visible as one logical row, while unmatched
successful custom destinations remain ad-hoc. Selecting a managed row chooses
among its routes; clearing its history never edits declarative configuration.
The full ranking, connection, deletion, and migration semantics are normative
in Host Mesh Contract v1.

The first implementation is a Python 3.11+ standard-library package with a
thin executable entry point. A compiled Rofi plugin would add ABI and build
coupling without improving a history of at most 100 records.

## Lifecycle

```text
Rofi callback
    |
    +-- render history (ROFI_RETV=0, 3, 10, 11, or 12)
    |
    +-- selected/custom destination
          |
          +-- detached Python worker
                 |
                 +-- ad-hoc / one route: terminal, then probe and record
                 +-- multiple routes: probe, choose, record, then terminal
```

The picker process never waits for SSH or a terminal. On selection it validates
the raw destination, starts itself again with `--worker <host>`, disconnects
the worker's standard streams, and exits. For ad-hoc destinations and managed
hosts with one route, the worker launches the terminal before running the same
bounded success-classification probe and history update. This removes probe
latency from the visible terminal-launch path without treating terminal launch
as connection evidence. Managed hosts with multiple routes still probe in
health-ranked order before launching, because route choice depends on that
result. Both worker and terminal use a new session and `close_fds`; terminal
launch is independent of Rofi and of the worker process lifetime.

The terminal is deliberately started even if the probe fails. This preserves
the interactive SSH experience: a user may still want to inspect a password,
host-key, or other SSH message. A failed probe only suppresses the history
write.

The SSH picker uses the existing explicit-user probe and its
`classify_probe` semantics, including recognized authentication and host-key
responses. Consumers that run a remote domain command use the separate
reached-host marker protocol; a nonzero domain exit after a valid marker is
not treated as a route failure.

## Rofi protocol

The executable handles Rofi's script callbacks:

- `ROFI_RETV=0`: render recorded rows.
- `ROFI_RETV=1`: use `ROFI_INFO` as the selected row's raw host, with the
  callback argument as a fallback; start a worker and return no rows.
- `ROFI_RETV=2`: use the callback argument as custom input, falling back to
  `ROFI_INPUT` for builds that expose it; this is the Ctrl+Enter
  (`kb-accept-custom`) path and starts a worker before returning no rows.
- `ROFI_RETV=3`: remove the selected `ROFI_INFO` host and render again.
- `ROFI_RETV=10`, `11`, or `12`: compatibility callbacks from already-open P8
  windows. Render the recent-only rows again without rewriting legacy
  `sortMode`, probing routes, launching a terminal, or applying callback-owned
  key semantics.

Compatibility callbacks 10, 11, and 12 render the current state without
discovery, route probing, terminal launch, or history mutation merely to
normalize the retired sort field. Their output
includes `keep-filter=true`, so Rofi preserves the active query, while omitting
`keep-selection` so Rofi selects the first eligible matching row. Callback
output continues to use the tab delimiter remembered from the initial render.

Rows put the raw host before the NUL option separator and also provide it as
both `info` and `meta`; selection therefore never depends on visible text.
Their `display` value contains two physical lines: the host, followed by
connection count and compact relative age, always age-first. The output
declares a tab record delimiter so the display newline remains inside one row.
The delimiter is declared using the default newline only on the initial render;
callback headers and rows use the remembered tab delimiter. The prompt is
simply `SSH`.

The initial and every re-rendered output contains `use-hot-keys=true`, which is
required for Rofi to emit custom-key callbacks. Plain Enter activates the
highlighted row; Ctrl+Enter is the reliable custom-input action. SSH leaves
Left/Right and Ctrl+B/Ctrl+F as Rofi-native filter-cursor actions because it
has no peer view. Rofi's default Tab and Shift+Tab row navigation remains
available. Escape and Ctrl+G are explicitly configured as cancellation keys;
there is no layered navigation or Escape-back behavior.

The state model is independent of protocol rendering, and subprocess argv
construction is independent of both. This keeps state/ranking, probe
classification, lifecycle, and Rofi dispatch unit-testable without a display
or network.

## State, migration, and concurrency

Generic state is `${XDG_STATE_HOME:-~/.local/state}/rofi-ssh-plus/history.json`.
Its schema is:

```json
{
  "version": 1,
  "sortMode": "recency",
  "hosts": [
    {"host": "example", "lastConnected": 1722743000123, "count": 5}
  ]
}
```

Records are validated on read. Host identity is case-insensitive and stored
case-folded; count must be positive and timestamps nonnegative integers.
Malformed records do not abort the whole history. A missing generic file is
initialized while holding the lock by importing valid data from the legacy DMS
file at `${XDG_STATE_HOME:-~/.local/state}/DankMaterialShell/plugins/sshPlus_state.json`.
The legacy file is read-only and is never imported again once the generic file
exists. Duplicate legacy identities merge by adding counts and retaining the
newest timestamp. Missing or invalid count/timestamp fields receive safe
defaults (`1` and `0`) so a valid host is not discarded merely for partial
metadata. Missing, invalid, and legacy `sortMode` values are accepted as
recency-only reads and are normalized on the next real write.

Every read-or-mutate operation opens a sibling lock file and takes an advisory
exclusive lock. Mutations serialize a complete current snapshot to a private
temporary file, flush and fsync it, then `os.replace` it into the target from
the same directory. The directory is fsynced when supported. This avoids lost
updates between picker and workers and avoids readers observing a partial JSON
file.

## Probe classification

The probe is exactly an argv sequence equivalent to:

```text
ssh -o BatchMode=yes -o ConnectTimeout=2 <host> true
```

Exit code 0 records the host. Nonzero results also record when stderr contains
one of the DMS-equivalent reached-server markers: `permission denied`, `host
key verification`, `remote host identification has changed`, or `userauth`.
This intentionally records password-auth and host-key cases after a real
server answers, while not recording DNS resolution, connection refusal,
network timeout, or missing-binary failures. A hard subprocess timeout is an
additional guard around SSH's own `ConnectTimeout` and scales with the
configured `ConnectionAttempts` bound.

## Input and security

Custom and callback destinations must be a single nonempty token, contain no
whitespace/control characters, and not begin with `-`. Every use of the host
in a subprocess is one argv element; no shell string is built and no host is
interpolated into `sh -c`. Terminal settings may contain a conventional
space-separated command prefix and are parsed with `shlex.split`; malformed or
empty values fall back to `ghostty`.

History is capped at 100 entries, with the oldest records dropped using
recency and deterministic non-frequency tie-breakers. Files and containing
directories are private where possible. The detached worker inherits the user's environment so XDG state,
terminal, and optional command settings remain consistent with the picker.
The supported optional knobs are `TERMINAL`, positive
`ROFI_SSH_PLUS_CONNECT_TIMEOUT`, and the single-executable
`ROFI_SSH_PLUS_SSH_COMMAND`.

## Current implementation non-goals

- Enumerating SSH configuration or `known_hosts`.
- SSH argument passthrough, per-host editing, or pinning. Declarative logical
  hosts, aliases, and routes are managed only through the Host Mesh contract.
- A native Rofi C plugin or dmenu compatibility wrapper.
- DMS/chezmoi integration, deployment, release automation, or network tests.
