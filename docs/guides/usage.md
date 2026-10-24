# Usage

For installation and the complete Rofi invocation, use [getting started](../getting-started.md).

The picker opens with configured logical hosts and recorded ad-hoc destinations
ordered strictly by most recent successful connection. Used destinations sort
by descending `lastConnected`; equal timestamps use deterministic host mesh
declaration/name tie-breakers and never use connection count. Never-used managed
hosts follow in Host Mesh declaration order. Connection count remains secondary
metadata after relative age. Plain Enter connects the highlighted listed host;
typed text only filters the list. A managed row tries its ordered routes and
records one logical-host usage after a route answers. The terminal opens even
when checks fail, so a password prompt or visible SSH error remains possible.

## Keys and actions

| Key/action | Behavior |
| --- | --- |
| Up/Down, Ctrl-P/Ctrl-N | Navigate rows using Rofi defaults |
| Left/Right | Move the filter cursor using Rofi defaults |
| Tab | Cycle to the next action |
| Shift+Tab | Select the previous action |
| Enter | Run the displayed action on the selected listed host |
| Escape, Ctrl+G | Close the picker |

The message shows `Enter:` with both actions and highlights the one Enter will
run. A divider separates `Tab: Cycle actions` on the same line; Tab never runs
an action. Notices follow after a blank line.
Host identity and search metadata precede the multiline display option in each
Rofi row, so Enter receives the typed host identity on a one-row list.

The selected row keeps a typed stable host identity in Rofi's `info` field and
its canonical host in `meta` for normal filtering; visible decoration never
drives selection. Each row reserves two physical lines: the destination is
primary and the secondary line contains relative age followed by connection
count. The active action name is carried in versioned `ROFI_DATA`; action
callbacks preserve both the filter and highlighted row. `ROFI_RETV=2` and
`ROFI_RETV=3` are visible no-ops, and callbacks 10, 11, and 12 from older
windows are harmless notices. Escape and Ctrl+G are native cancellation keys.
SSH has no peer view, so Left/Right and Ctrl+B/Ctrl+F retain Rofi's native
filter-cursor behavior.

A hostname is compared case-insensitively and stored in its canonical lower-case
form. Connection counts are retained for metadata and migration but never
participate in ordering. Legacy, missing, or invalid `sortMode` is read as
recent-only and normalized on the next real write.

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
[Host Mesh Contract v1](../reference/host-mesh-v1.md) for domain commands. A marker
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
