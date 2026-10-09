# Mesh CLI startup

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
[1.008](evidence/2026-10-09-mesh-startup/baseline-1.json) /
[1.068](evidence/2026-10-09-mesh-startup/baseline-2.json) CPU seconds before and
[0.873](evidence/2026-10-09-mesh-startup/candidate-1.json) /
[0.897](evidence/2026-10-09-mesh-startup/candidate-2.json) afterward.
Mean CPU per invocation falls from 51.9 to 44.2 ms, about 15%. All replies have
the same digest; module hashes identify the candidate before its commit.
The absolute whole-service saving at a fifteen-second cadence is small.

All 76 source tests pass, including a fresh process that serves Mesh while
picker/history/launcher imports are unavailable, package-export compatibility
and the existing real executable/picker/worker cases. The Host Mesh v1 bundle
digest remains `258e8df0562aea18a20db5378b3335b03332e3df0c0709faf49ccfbffa5c3e10`.
This change adds no watch API or polling policy. Provider source acceptance is
separate from downstream installed performance and managed deployment.
