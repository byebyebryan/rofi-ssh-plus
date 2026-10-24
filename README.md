# SSH Plus

A Rofi picker for configured SSH hosts and destinations that have answered a
reachability check. It also exposes the public Host Mesh v1 process interface
used by other tools for logical hosts, routes and route health.

[Project showcase](https://dev.byebyebryan.com/fleet-plus/projects/ssh-plus/) ·
[Setup and usage](docs/usage.md) · [Documentation](docs/README.md)

## Install and launch

Requires Python 3.11+, Rofi 2.0+, OpenSSH and a terminal accepting `-e`
(`TERMINAL`, otherwise Ghostty). The selected Mesh Plus authority package must
be installed in the Python environment used by the checkout wrapper. See
[configuration](docs/configuration.md) for backend selection and prerequisites.

From a checkout, put an absolute link on `PATH` and launch the Rofi script mode:

```sh
mkdir -p ~/.local/bin
ln -s /absolute/path/to/rofi-ssh-plus/bin/rofi-ssh-plus ~/.local/bin/rofi-ssh-plus
```

The [setup guide](docs/usage.md#install-and-invoke) gives the complete Rofi
invocation and key bindings. No daemon or compiled plugin is required.

## Use

- Enter connects the selected listed host; text filters the list.
- Tab / Shift+Tab cycle Connect and Forget recent history without executing them.
- Escape / Ctrl+G close the picker; Left/Right edit the filter.
- Destinations sort by most recent successful connection; count is metadata only.

Managed rows use configured ordered routes. Ad-hoc history does not discover
new logical peers. The picker does not enumerate SSH config or `known_hosts`.
See [usage](docs/usage.md) for row/history behavior and reachability limits.

## Configure hosts or consume Host Mesh

Mesh Plus owns the shared authority implementation; SSH Plus owns the canonical
contract/facade, connection UX and successful-connection history. Configuration
is endpoint-specific and directional: a peer readable from this host receives
no automatic reverse route.

```sh
rofi-ssh-plus mesh list --json
```

Use [configuration](docs/configuration.md) for backend/state ownership and
[Host Mesh v1](docs/HOST_MESH_V1.md) for exact config, CLI and report semantics.
Agent Plus native entry and Observer/Tmux reads have independent requirements.

## Develop

```sh
./scripts/check
```

The deterministic gate does not connect to network hosts or require a Rofi
display. See [development](docs/development.md) for tools and conformance gates.
Managed artifacts and fleet acceptance belong to the deployment owner.
Shared presentation lives at [Fleet Plus](https://dev.byebyebryan.com/fleet-plus/).
