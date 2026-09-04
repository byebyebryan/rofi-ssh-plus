# Design: rofi-ssh-plus

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
SSH frequency ranking.

The target mesh-aware picker retains the existing Frequent and Recent lenses.
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
                 +-- bounded explicit-user SSH probe (or consumer marker command)
                 +-- record success, if reached
                 +-- detached terminal: <terminal> -e ssh <host>
```

The picker process never waits for SSH or a terminal. On selection it validates
the raw destination, starts itself again with `--worker <host>`, disconnects
the worker's standard streams, and exits. The worker probes synchronously so
the state update occurs before its terminal launch. Both worker and terminal
use a new session and `close_fds`; terminal launch is therefore independent of
Rofi and of the worker process lifetime.

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
- `ROFI_RETV=10`: toggle persisted sort mode and render again.
- `ROFI_RETV=11`: move to the next persisted sort lens and render again. This
  is the managed Right binding.
- `ROFI_RETV=12`: move to the previous persisted sort lens and render again.
  This is the managed Left binding.

Rows put the raw host before the NUL option separator and also provide it as
both `info` and `meta`; selection therefore never depends on visible text.
Their `display` value contains two physical lines: the host, followed by
connection count and compact relative age. Frequency detail is count-first;
recency detail is age-first. The output declares a tab record delimiter so the
display newline remains inside one row. The delimiter is declared using the
default newline only on the initial render; callback headers and rows use the
remembered tab delimiter. The prompt identifies the active lens as
`SSH › Frequent` or `SSH › Recent`.

The initial and every re-rendered output contains `use-hot-keys=true`, which is
required for Rofi to emit custom-key callbacks. Plain Enter activates the
highlighted row; Ctrl+Enter is the reliable custom-input action. The managed
invocation assigns Right and Left to callbacks 11 and 12, and remaps text
cursor movement to Ctrl+F/Ctrl+B. Rofi's default Tab and Shift+Tab row
navigation remains available. Alt+S remains callback 10 as a compatibility
toggle. Escape and Ctrl+G are explicitly configured as cancellation keys;
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
  "sortMode": "frequency",
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
metadata.

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

History is capped at 100 entries, with the least useful records dropped using
the active ordering. Files and containing directories are private where
possible. The detached worker inherits the user's environment so XDG state,
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
