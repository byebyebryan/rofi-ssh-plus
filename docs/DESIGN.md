# SSH Plus design

SSH Plus owns a small recent-destination picker and the public Host Mesh v1
facade. Mesh Plus owns shared logical host authority and route health. Native
provider entry, observation and generic tmux clients are independent consumers.

## Current interaction

There is one recent-only host list. Managed logical hosts and recorded ad-hoc
destinations are leaf rows. Successful usage sorts by descending `lastConnected`;
count remains display metadata. Never-used managed hosts follow in declaration
order, with deterministic tie-breakers.

Enter runs the visible action against the selected typed identity. Tab and
Shift+Tab cycle Connect/Forget; they do not execute. Left/Right edit the filter.
Escape/Ctrl+G use native Rofi cancellation. Old callback values produce harmless
notices without probing, launching or rewriting history.

Typed row identity lives in Rofi `info`, canonical search metadata in `meta`,
and action state in versioned `ROFI_DATA`. Decoration never drives selection.
Callbacks preserve filter and highlighted identity.

## Authority, usage and process lifetime

Host configuration is explicit and directional. One selected authority supplies
identity, aliases, ordered routes and revision-bound health. Successful SSH
connection history remains private to the picker. Neither history nor incoming
connections grants a peer route.

The selected backend is explicit, with typed failure and no automatic fallback.
The legacy rollback backend preserves original paths/state semantics. Consumers
call the public Host Mesh CLI rather than reading private history/state.

The picker starts a detached worker. Single-route/ad-hoc entry launches the
terminal before a separate bounded history probe; multiple routes are probed
first for fallback selection. The terminal opens even after failed checks so
interactive authentication or errors remain visible. Commands use argv, not a
shell, and bounded input excludes SSH option injection.

Picker reachability/history rules and authenticated background route reports
are different observations. A reached marker followed by domain failure does
not make a network route bad. See [Host Mesh v1](HOST_MESH_V1.md).

## Validation and retained history

[Development](development.md) separates deterministic checks, public boundary
conformance, installed behavior and live/graphical proof. Source tests do not
establish a new deployed artifact or fleet acceptance.

The [earlier design ledger](history/design/DESIGN-before-20261024.md) retains
P6–P9 rollout claims, navigation transitions and probe lessons in their original
scope. Current setup and settings live in [usage](usage.md) and
[configuration](configuration.md), rather than that chronology.
