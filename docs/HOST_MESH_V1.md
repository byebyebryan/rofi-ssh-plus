# Host Mesh Contract v1

Status: implemented in the current source; no tagged release has published
this contract yet.

This contract makes `rofi-ssh-plus` the host and route authority for the Rofi
SSH, tmux, and agent pickers. It is a local process contract, not a network
service. Consumers invoke the executable and exchange versioned JSON; they do
not import its Python package or read its private state files.

The canonical consumer executable is `rofi-ssh-plus`, resolved through
`PATH`. A suite deployment installs that command independently of the Rofi
script-mode symlink; `~/.config/rofi/scripts/ssh-plus` is a UI entry point, not
an integration path. A missing command permits an explicitly documented
local-only fallback. An incompatible or malformed command is an error.

## Ownership and boundary

`rofi-ssh-plus` owns:

- stable logical host identity and display labels;
- aliases used to correlate native hostnames with logical hosts;
- ordered SSH route candidates for each remote host;
- connection policy and last-known route health; and
- explicit user connection history used by the SSH picker.

It does not configure a VPN, DNS, SSH credentials, host keys, or
`~/.ssh/config`. "Mesh" means that several SSH destinations may identify
different paths to one logical host. It does not mean that this project owns
the underlying network mesh.

Higher layers own the commands they run through SSH. In particular,
`rofi-tmux-plus` owns tmux commands and `rofi-agent-plus` owns provider
probes. `rofi-ssh-plus` provides route candidates but does not become a generic
remote-command executor.

## Configuration

The canonical configuration file is
`${XDG_CONFIG_HOME:-~/.config}/rofi-ssh-plus/config.toml`. A representative
configuration is:

```toml
schema_version = 1
local_id = "desktop-a"
local_display = "Desktop A"
local_aliases = ["desktop-a-native"]

[ssh]
executable = "ssh"
connect_timeout_seconds = 2
connection_attempts = 1
route_health_ttl_seconds = 300

[[hosts]]
id = "desktop-b"
display = "Desktop B"
routes = ["desktop-b-vpn.example", "desktop-b.lan"]
aliases = ["desktop-b-native"]
```

The local host is synthesized from the `local_*` fields and is never reached
through SSH. If `local_id` is omitted, the case-folded short system hostname is
used. Its output aliases contain the configured values plus the current full
and short system hostnames, deduplicated case-insensitively. If the file is
absent, the mesh contains only that inferred local host.

Host IDs are stable, case-insensitive identifiers matching
`[A-Za-z0-9][A-Za-z0-9_.-]*`. Their canonical representation is case-folded.
Display labels preserve user spelling and are not identities. Each remote host
has at least one ordered route. A route is one SSH destination argv element:
it must be nonempty, must not start with `-`, and must not contain whitespace or
control characters. SSH aliases, `user@host`, and bracketed IPv6 destinations
remain valid.

Aliases obey the same single-token and control-character restrictions. Host
IDs and aliases compare by Unicode case-folded value. Route spelling is
preserved exactly for SSH invocation, while route correlation uses the
case-folded whole token. This deliberately treats destinations that differ only
by username case as conflicting configuration instead of guessing whether a
particular SSH server distinguishes them. Consumers use these same correlation
rules for custom input and native-host matching.

Host IDs, aliases, and route destinations must map unambiguously to one logical
host. Duplicate IDs or values that would correlate to two hosts make the
configuration invalid rather than allowing a consumer-dependent choice.

The SSH executable is one nonempty argv element. Connection timeout is an
integer from 1 through 60 seconds, connection attempts from 1 through 10, and
route-health TTL from 1 through 86400 seconds. Unknown keys, wrong types, and
out-of-range values make a present configuration invalid; they do not trigger
silent defaults.

## Consumer CLI

### List the mesh

```text
rofi-ssh-plus mesh list --json
```

The executable distinguishes the public CLI from Rofi script callbacks by the
argv shape. With `ROFI_RETV` present, exactly one argv token `mesh` remains a
literal picker-row selection; any following token enters the Host Mesh parser,
including an invalid subcommand that returns the standard `invalid_input`
envelope. Without `ROFI_RETV`, the existing `mesh ...` CLI behavior remains
unchanged. This keeps valid `mesh list` and `mesh report-route` calls on the
public contract path when invoked by another picker.

Successful output has this shape:

```json
{
  "schemaVersion": 1,
  "generatedAt": 1722743000123,
  "meshRevision": "sha256:0123456789abcdef",
  "localHostId": "desktop-a",
  "sshPolicy": {
    "executable": "ssh",
    "connectTimeoutSeconds": 2,
    "connectionAttempts": 1,
    "routeHealthTtlSeconds": 300
  },
  "hosts": [
    {
      "id": "desktop-a",
      "display": "Desktop A",
      "local": true,
      "aliases": ["desktop-a-native"],
      "routes": []
    },
    {
      "id": "desktop-b",
      "display": "Desktop B",
      "local": false,
      "aliases": ["desktop-b-native"],
      "routes": [
        {
          "destination": "desktop-b-vpn.example",
          "configuredIndex": 0,
          "lastReachableAt": 1722742900000,
          "lastUnreachableAt": null
        },
        {
          "destination": "desktop-b.lan",
          "configuredIndex": 1,
          "lastReachableAt": null,
          "lastUnreachableAt": null
        }
      ]
    }
  ]
}
```

All timestamps are Unix milliseconds. `meshRevision` is an opaque digest of
the normalized identity, route, and SSH-policy configuration. It changes when
that configuration changes and does not change for usage-history or
route-health updates. There is exactly one local descriptor, and it is first.
Remote hosts follow declaration order.

A remote host's `routes` array is the current recommended attempt order;
`configuredIndex` retains the deterministic base order. A route whose newest
health event is `unreachable` is moved behind the other configured routes for
`routeHealthTtlSeconds`. After that bounded demotion expires, configured order
is restored so a preferred path is retried. Positive reports do not permanently
promote a fallback over the configured preference.

Consumers use `id` in caches, row metadata, and cross-picker calls. They must
not substitute a route destination for the logical ID. Aliases are correlation
inputs, not additional destinations.

### Report route health

```text
rofi-ssh-plus mesh report-route --json \
  --host desktop-b \
  --route desktop-b-vpn.example \
  --status reachable \
  --source rofi-tmux-plus \
  --mesh-revision sha256:0123456789abcdef \
  --observed-at 1722742999000
```

`status` is `reachable` or `unreachable`. The host and route must exist in the
current mesh. `source` is a bounded diagnostic label; it does not affect SSH
history ranking. `meshRevision` must equal the current revision, preventing a
late observation from a replaced route definition. Required `observedAt` is the
local Unix-millisecond time at which the SSH attempt completed. Success returns:

```json
{"schemaVersion":1,"ok":true,"accepted":true}
```

A report that is not newer than the newest recorded outcome for that route
succeeds with `accepted: false` and does not mutate health. A timestamp more
than five minutes ahead of the receiving process is invalid input. The owner
stores reachable and unreachable observation times monotonically; process
scheduling therefore cannot make a late result look newer than the attempt
that produced it.

A consumer reports `reachable` once an authenticated remote shell emits the
reached-host marker below, even when the domain command subsequently fails or
reports that a tool is missing. It reports `unreachable` only for a classified
transport failure before that marker. Authentication refusal, host-key
refusal, and any other result that cannot safely distinguish transport from
policy produce no health report. A nonzero remote tmux or provider command
must never poison route health.

Route reports are hints, not leases. Another consumer may discover a different
working route immediately afterward. Consumers retry the ordered candidates
they received and remain correct if route preference changes between calls.

## Reached-host protocol

Every consumer that combines route selection with a domain command uses the
same version-1 marker protocol instead of interpreting the SSH exit code as a
domain result:

1. Generate an unpredictable lowercase hexadecimal nonce containing at least
   128 bits.
2. Invoke the remote POSIX shell with a wrapper whose first operation writes
   this exact line to standard error, where `NONCE` is the generated value:

   ```text
   <RS>ROFI_PLUS_REACHED_V1:NONCE<US>\n
   ```

   `<RS>` and `<US>` are bytes `0x1e` and `0x1f`. The wrapper then executes the
   domain argv without reparsing it as user-supplied shell source.
3. Accept exactly one marker containing the invocation's nonce and remove only
   that marker from captured diagnostics. Similar remote output, a marker with
   another nonce, or an incomplete marker is ordinary untrusted stderr.
4. A valid marker means SSH authenticated and started the remote wrapper. The
   final exit status and remaining stdout/stderr belong to the domain command.
   It terminates route selection: a consumer must not run the domain command on
   another route merely because that command returned nonzero.
5. Without the marker, the consumer has no domain result. It may try the next
   route, but it reports `unreachable` only when its tested OpenSSH classifier
   identifies a transport failure. Otherwise it sends no route report.

Interactive attachment is asynchronous and cannot itself provide a result to
the launching JSON command. A management operation first selects a route using
a bounded marked command, then launches the terminal against that route. A
terminal-side wrapper may attempt later candidates after a transport failure,
but `terminalLaunched` means only that the local terminal process was started.

## Target SSH picker behavior

Host Mesh does not add another top-level SSH view. `SSH › Frequent` and
`SSH › Recent` each show one row per configured remote logical host plus
successful ad-hoc destinations that do not correlate to a managed host. The
local descriptor is not an SSH destination and is omitted.

Configured hosts are visible before their first connection. They have count
zero and an unknown age. Frequent sorts by count, last connection, then stable
display identity. Recent sorts rows with a connection time newest first, then
never-connected managed hosts in mesh declaration order. Background route
health never participates in either usage ranking.

Selecting a managed host tries its recommended routes in order using SSH
Plus's explicit-user reachability probe. The first route that answers under the
existing interactive-history rules is used for the terminal and increments
the logical host's usage once. If no route answers, the terminal still opens
against the first recommended route so the user can see authentication,
host-key, or network diagnostics, but usage is not recorded. A custom input
that unambiguously matches a managed ID, alias, or route is folded into that
logical host; any other successfully reached input remains ad-hoc.

Shift+Delete removes an ad-hoc history row. On a managed host it clears only
the usage counters; declarative host identity and routes remain and the row is
still visible. The private history migration merges all unambiguous legacy
route records into their logical host by summing counts and retaining the
newest connection time. Ambiguous or unmatched records remain ad-hoc rather
than being discarded.

## Usage history versus route health

The SSH picker's frequency and recency statistics measure explicit user
connections launched through SSH Plus. Background discovery from Tmux Plus or
Agent Plus updates route health only. It must not increment connection count
or `lastConnected`.

The current version-1 history file remains private implementation state. Its
mesh-aware migration correlates raw destinations to logical host IDs using the
rules above, but neither the migrated schema nor its filesystem layout is part
of this contract. Consumers use only the commands above.

## Errors and compatibility

JSON commands write exactly one JSON document to stdout. On a contract,
configuration, or persistence failure they return nonzero and write an error
document of this form:

```json
{
  "schemaVersion": 1,
  "ok": false,
  "error": {
    "code": "invalid_config",
    "message": "host IDs must be unique"
  }
}
```

Human diagnostics may additionally be written to stderr. Consumers ignore
unknown fields within schema version 1 and reject a schema version they do not
support. A missing executable may be treated as local-only capability by a
consumer; malformed or unsupported output must be surfaced rather than
silently reinterpreted.

Stable version-1 error codes are `invalid_input`, `invalid_config`,
`unsupported_schema`, `unknown_host`, `unknown_route`, `stale_mesh`, and
`persistence_failed`.

## Security and privacy

- Consumers build SSH argv arrays and use the advertised executable as one
  argv element. Arbitrary SSH option strings are not accepted from this
  contract.
- Background discovery and noninteractive management use `BatchMode=yes`, a
  bounded connection timeout, and no automatic host-key acceptance.
- Route destinations and aliases may be private infrastructure data. Examples
  committed to public repositories use generic names.
- Dynamic host, route, and error text is treated as untrusted and is escaped
  before entering shell commands, Rofi markup, logs, or terminal titles.

## Required conformance fixtures

The version-1 implementation publishes deterministic fixtures covering:

- a local-only mesh and a multi-route remote mesh;
- configured-order restoration after a route-health demotion expires;
- accepted, duplicate, out-of-order, future-dated, and stale-revision reports;
- valid, wrong-nonce, incomplete, and absent reached-host markers around both
  zero and nonzero domain exits;
- invalid and ambiguous host, alias, and route configuration;
- migration of multiple legacy routes into one managed logical host while
  retaining unmatched ad-hoc history; and
- the standard success and every stable error envelope.

Consumer repositories test against these published fixtures or executable
fakes. They do not import SSH Plus internals or read its private state.

## Adoption sequence

1. The current source provides strict configuration parsing and the two JSON
   commands above.
2. Route-health events are persisted separately from explicit user usage.
3. The SSH picker collapses managed routes and aliases to one logical host
   while retaining ad-hoc successful destinations.
4. Deterministic producer fixtures cover the list, report, marker, migration,
   and error-envelope cases.
5. Agent Plus and Tmux Plus consume this contract in their respective
   integration checkpoints; they do not import SSH Plus internals.
