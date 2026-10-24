# Getting started

Requires Python 3.11+, Rofi 2.0+, OpenSSH and a terminal accepting `-e`
(`TERMINAL`, otherwise Ghostty). Install a compatible Mesh Plus authority package
in the Python environment used by the checkout wrapper; it invokes `python3`
from PATH. See [configuration](guides/configuration.md).

From a maintained checkout, put the public command on PATH:

```sh
mkdir -p ~/.local/bin
ln -s /absolute/path/to/rofi-ssh-plus/bin/rofi-ssh-plus ~/.local/bin/rofi-ssh-plus
rofi-ssh-plus mesh list --json
```

The logical host catalog is explicit and directional. An unconfigured endpoint
does not infer peers from SSH config, history or incoming connections. Setup
does not require an Observer service or compiled plugin.

## Launch Rofi

A direct invocation is:

```sh
rofi -show ssh-plus \
  -modes "ssh-plus:/absolute/path/to/rofi-ssh-plus/bin/rofi-ssh-plus" \
  -theme-str 'entry { placeholder: "Filter hosts · Enter connect · Tab actions · Esc close"; }' \
  -kb-cancel Escape,Control+g \
  -kb-element-next "" \
  -kb-element-prev "" \
  -kb-custom-7 Tab \
  -kb-custom-8 ISO_Left_Tab \
  -kb-custom-1 "" \
  -kb-custom-2 "" \
  -kb-custom-3 "" \
  -kb-custom-4 "" \
  -kb-accept-custom "" \
  -kb-delete-entry "" \
  -eh 2
```

Use [usage](guides/usage.md) for keys and reachability semantics,
[configuration](guides/configuration.md) for backend/state ownership and
[Host Mesh v1](reference/host-mesh-v1.md) for exact fields and process envelopes.
