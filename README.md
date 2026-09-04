# rofi-ssh-plus

`rofi-ssh-plus` is a Rofi script-mode picker for SSH destinations that have
actually answered an SSH reachability check. It does not enumerate
`known_hosts` or SSH configuration, so the list stays small and useful.

The current release is history-only. A proposed, not-yet-implemented
[Host Mesh Contract v1](docs/HOST_MESH_V1.md) would make this project the
logical-host and route authority shared by `rofi-tmux-plus` and
`rofi-agent-plus` without exposing its private state files.

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
  -theme-str 'entry { placeholder: "Filter or type host · ←/→ order · Ctrl+Enter new"; }' \
  -kb-custom-1 Alt+s \
  -kb-move-char-forward Control+f \
  -kb-move-char-back Control+b \
  -kb-custom-2 Right \
  -kb-custom-3 Left \
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
  -theme-str 'entry { placeholder: "Filter or type host · ←/→ order · Ctrl+Enter new"; }' \
  -kb-custom-1 Alt+s \
  -kb-move-char-forward Control+f -kb-move-char-back Control+b \
  -kb-custom-2 Right -kb-custom-3 Left \
  -kb-cancel Escape,Control+g \
  -kb-accept-custom Control+Return \
  -eh 2
```

The picker opens with recorded destinations ordered by frequency and labels the
active lens as `SSH › Frequent` (or `SSH › Recent`) in the prompt. Right and
Left switch to the next or previous lens, wrapping and persisting the choice;
`Alt+s` remains a compatibility alias for switching. Type a new destination and
press Ctrl+Enter to launch it; plain Enter selects the highlighted row. It is
added only after the detached worker confirms that a server answered. The
terminal opens even when the check fails, so a password prompt or a visible SSH
error remains possible.

## Keys and actions

| Key/action | Behavior |
| --- | --- |
| Up/Down, Ctrl-P/Ctrl-N, Tab/Shift+Tab | Navigate rows using Rofi defaults |
| Right | Switch to the next ordering lens (frequency → recency → frequency) |
| Left | Switch to the previous ordering lens (frequency → recency → frequency) |
| Enter | Connect to the selected recorded host |
| Typed input + Ctrl+Enter | Probe and connect to a new destination |
| Shift+Delete | Remove the selected destination from history |
| `Alt+s` (`-kb-custom-1 Alt+s`) | Compatibility alias for switching ordering |
| Escape, Ctrl+G | Close the picker |

The selected row keeps its raw destination in Rofi's `info` and `meta` fields;
visible decoration never drives selection. Each row reserves two physical
lines: the destination is primary and the secondary line contains connection
count and relative age. The detail order follows the active lens: frequency
first in `Frequent`, age first in `Recent`. The invocation remaps text-cursor
movement to Ctrl+F/Ctrl+B so the arrow keys can switch lenses. Escape and
Ctrl+G are explicitly configured as cancellation keys; Tab and Shift+Tab
retain Rofi's normal row navigation.

Frequency ordering is count descending, then last-connected descending. Recency
ordering is last-connected descending, then count descending. A hostname is
compared case-insensitively and stored in its canonical lower-case form.

## State and migration

The generic state file is:

```text
${XDG_STATE_HOME:-~/.local/state}/rofi-ssh-plus/history.json
```

It is a versioned JSON object containing `version`, `sortMode`, and `hosts`.
Each host has `host`, millisecond `lastConnected`, and positive `count`.
The parent directory is private (`0700`), the state and lock files are private
(`0600`), updates use an advisory lock and an atomic same-directory replace.

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

Optional environment configuration is intentionally narrow:

- `TERMINAL` selects the terminal command prefix (parsed with `shlex.split`).
- `ROFI_SSH_PLUS_CONNECT_TIMEOUT` sets the positive probe timeout in seconds;
  the default is `2`.
- `ROFI_SSH_PLUS_SSH_COMMAND` selects one SSH executable path for probing and
  launch; it is passed as one argv element and does not accept extra options.

The picker starts a detached worker, and the worker starts the terminal in a
new session with standard input/output/error disconnected. Rofi can therefore
exit immediately and the terminal does not depend on the worker's lifetime.

## Limits and security choices

- History is capped at 100 records, dropping the lowest-ranked records when
  necessary.
- Input must be one nonempty token with no whitespace or control characters
  and must not begin with `-`; this blocks accidental SSH option injection.
- SSH argument passthrough, host editing/pinning, and config/known-hosts
  discovery are intentionally out of scope.
- A successful reachability probe is not proof that authentication will
  complete in the interactive terminal. It only proves that the destination
  answered in a way consistent with a real SSH server.

Run `./scripts/check` for deterministic validation. It does not connect to
network hosts or require an active Rofi display session.
