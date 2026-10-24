# Mesh CLI startup

> Historical record. This document preserves its original checkpoint and may describe retired providers, interfaces or plans. Use the [current documentation](../../README.md) for supported setup and behavior.

2026-10-09. Tmux Observer invokes the public Mesh CLI every fifteen seconds.
Fresh processes previously imported the picker, launcher and history state even
when serving `mesh list --json`. Mesh now imports its own configuration/health
path; worker and picker imports happen when those commands are selected.
Package exports retain their original objects through lazy resolution. The
picker's `spawn_worker` injection seam remains available.

`scripts/measure-mesh-startup` runs twenty fresh public CLI processes with the
canonical three-host configuration and private configuration/health directories.
It checks the configured host identities and hashes replies after removing only
`generatedAt`. It reads no ordinary preferences and starts no SSH or terminal.

Matched Python 3.14 measurements use
[1.008](../../evidence/2026-10-09-mesh-startup/baseline-1.json) /
[1.068](../../evidence/2026-10-09-mesh-startup/baseline-2.json) CPU seconds before and
[0.873](../../evidence/2026-10-09-mesh-startup/candidate-1.json) /
[0.897](../../evidence/2026-10-09-mesh-startup/candidate-2.json) afterward.
Mean CPU per invocation falls from 51.9 to 44.2 ms, about 15%. All replies have
the same digest; module hashes identify the candidate before its commit.
The absolute whole-service saving at a fifteen-second cadence is small.

All 76 source tests pass, including a fresh process that serves Mesh while
picker/history/launcher imports are unavailable, package-export compatibility
and the existing real executable/picker/worker cases. The Host Mesh v1 bundle
digest remains `258e8df0562aea18a20db5378b3335b03332e3df0c0709faf49ccfbffa5c3e10`.
This change adds no watch API or polling policy. Provider source acceptance is
separate from downstream installed performance and managed deployment.

## Managed authority adoption records

[Default-authority adoption](../../evidence/2026-10-09-ssh-mesh-default.json) and
[public-facade adoption](../../evidence/2026-10-09-ssh-mesh-facade.json) retain their
original environment, hashes and outcome limits. Config, routes and authority
are independent of recent-use history. Connect/Forget uses the accepted action
cycle; Left/Right and Ctrl+B/F remain native filter editing. Forgotten ad-hoc
rows disappear while managed hosts remain declared. Legacy `frequency` migrates
to semantic recency only on a real state write; no history migration occurs here.
[P8/P9 rollout history](https://github.com/byebyebryan/dotfiles/blob/5ff8b412a45b69cac64b8eb356444e6cf0705012/docs/rofi-plus-p9-cli-contracts.md) preserves the original
suite cutover. Current contract authority is [Host Mesh v1](../../HOST_MESH_V1.md), not
a dotfiles status ledger. Physical/UI acceptance and captured synthetic probes
remain distinct.
