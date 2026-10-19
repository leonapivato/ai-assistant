# A hub in a container

You end this page with one person's hub and its gateway running in a container of
their own, reached through the sign-in edge on the box's loopback.

This is the hosted setup's unit (#3142): one container per person, holding their
hub, the gateway in front of it, and the keyring their connections are stored in.
A self-hoster can use it the same way for their own hub. It assumes you have read
[`first-run.md`](first-run.md), because everything the hub and the gateway say there
they say here too.

## What is in it, and what is not

- **The hub and its gateway, as one unit.** The gateway reaches the hub over the
  local socket inside the container. Nothing configures a remote listener, and the
  container refuses to start if the env file asks for one.
- **A genuine keyring.** A session bus and a headless `gnome-keyring-daemon` on it,
  as on the box: the SecretService backend the secret store requires (ADR-0125 §7),
  unlocked at every start with a passphrase you mount.
- **No secret.** The image holds no model key, no keyring passphrase and no backup
  passphrase. They arrive when the container starts.
- **No data.** The data directory and the keyring are volumes, so a new image starts
  on the directory the old one served (ADR-0326 §3:1).

One door: the gateway's hosted listener, on the container's own private address,
published to the host's loopback alone (ADR-0327 §5). The sign-in edge forwards to
that loopback port, and every request it forwards carries its signed assertion.

## 1. Build the image

From a clean checkout of the commit you want:

```bash
just container-image
```

It refuses a tree with uncommitted or untracked changes, because the image is
labelled with the commit and must contain it. It builds the wheel from that tree,
exports `uv.lock`'s runtime set as pinned, hashed requirements, and installs both
with no resolution — the same set `just deploy-hub` installs on a box. The image is
tagged `ai-assistant-hub:<the commit's first twelve characters>`; pass a tag to
name it yourself.

## 2. Write the env file and the passphrase

Each person gets a directory on the box holding two files, and two volumes.

**The env file** is Docker's `--env-file` format: one `NAME=value` per line, no
quotes, no `export`. Each line becomes a variable in the container's environment,
which is where the model key has to be (first-run.md, step 3):

```bash
ANTHROPIC_API_KEY=sk-ant-...
ASSISTANT_GATEWAY_HOSTED_HOST_NAME=alice.example.com
ASSISTANT_GATEWAY_HOSTED_DEVICE=alice-web
ASSISTANT_GATEWAY_EDGE_PUBLIC_KEYS=<the edge's Ed25519 public key, RFC 8037 x>
ASSISTANT_GATEWAY_EDGE_ISSUER=<the iss the edge signs>
ASSISTANT_GATEWAY_EDGE_AUDIENCE=<the aud naming this hub>
ASSISTANT_GATEWAY_EDGE_SUBJECT=<the edge's id for this person's account>
```

The hosted listener is always on in this container, so the six hosted and edge
settings are required: the hub refuses to start without them, and says which is
missing. Three things stay **out** of the env file:

- `ASSISTANT_GATEWAY_HOSTED_ADDRESS`. The container binds its own address, which is
  assigned when it starts, so it reads it then. Set it only to name one address
  explicitly; a loopback one is refused.
- `ASSISTANT_DATA_DIR`. The image pins it to the volume at `/data`, and a value
  that moves it is refused rather than obeyed.
- `ASSISTANT_HUB_REMOTE_ADDRESS`, `ASSISTANT_GATEWAY_REMOTE_ADDRESS` and
  `ASSISTANT_REMOTE_HUB_ADDRESS`. Each is refused.

Choose `ASSISTANT_GATEWAY_HOSTED_DEVICE` once the hub is up (step 5): it must be a
name no other device of the hub holds (ADR-0327 §10).

**The passphrase file** holds the keyring's passphrase and nothing else. One
trailing newline is ignored. The container runs as uid 10001, which must be able to
read it:

```bash
install -m 0400 -o 10001 -g 10001 /dev/stdin /srv/hubs/alice/keyring-passphrase
```

Keep it with the person's backup passphrase. A keyring volume opened with any
other passphrase stays locked, and the container refuses to start on it.

## 3. Run it

On a box you operate for other people, do not run it by hand: the deploy path below
runs it under systemd, and every later upgrade backs it up first. By hand, for one hub
of your own:

```bash
docker volume create alice-data
docker volume create alice-keyring
docker run --detach --name hub-alice \
    --env-file /srv/hubs/alice/hub.env \
    --volume alice-data:/data \
    --volume alice-keyring:/home/assistant/.local/share/keyrings \
    --volume /srv/hubs/alice/keyring-passphrase:/run/secrets/keyring-passphrase:ro \
    --publish 127.0.0.1:8501:8423 \
    --stop-timeout 90 \
    ai-assistant-hub:<commit>
```

What each line holds:

- **The two volumes** are the person's data directory and keyring. Named volumes are
  the simple case: Docker gives an empty one the image's owner and `0700` mode,
  which the hub's check on its directory requires. A bind-mounted directory must be
  owned by uid 10001 and writable by nobody else. The container refuses to start
  where either path is not mounted, because the data would then live in the
  container's own layer and be gone with it.
- **`--publish 127.0.0.1:8501:8423`** is the door. The left half is the host's
  loopback and a port of your choosing, one per person; it is where the edge
  forwards this person's requests. Never publish it without the `127.0.0.1:`.
- **`--stop-timeout 90`** gives the hub room to drain. ADR-0083 §3's D2 asks for
  `shutdown_drain_seconds` plus thirty seconds, which is sixty by default; Docker's
  own default of ten would cut every drain short.

Run it on a bridge network, Docker's default, and never on the host's own network
(`--network host`): there the hosted listener would bind one of the box's own
addresses. The container refuses to start where it sees more than one address
besides loopback, which on a box running Docker is always true of the host's
network, but that is a count and not a guarantee — a host with one private address
and no bridge would pass it.

### On a box, the deploy path runs it

`scripts/deploy_container.py` (`just deploy-container`) builds, backs up, replaces and
verifies one person's container as one act, from a machine that has no container
runtime, over ssh as root:

```bash
just deploy-container alice box.example.com --port 8501   # the first install
just deploy-container alice box.example.com               # every deploy after it
```

The box needs Docker, systemd, `curl` and `iptables`. For each person it reads a
directory the operator writes by hand, `/srv/hubs/<person>/` (`--hubs-dir` moves it, for
every person on the box at once), owned by root and writable by root alone:

| Path | Who writes it | Owner and mode |
| --- | --- | --- |
| `hub.env` | The operator: the env file of step 2 | root, `0600` |
| `keyring-passphrase` | The operator, as in step 2 | uid 10001, `0400` |
| `backup-passphrase` | The operator, the same way: the key to every backup | uid 10001, `0400` |
| `unit.env` | The deploy alone: the image id the unit runs, and the port | root, `0644` |
| `backups/` | The deploy: one artifact per deploy, never deleted | uid 10001, `0700` |

The deploy never creates, reads or prints a passphrase. It refuses, before it stops
anything, a passphrase file that is missing, empty, owned by another uid or readable by
anyone else, and keep a copy of each off the box: the backup passphrase is the only key
to the artifacts (ADR-0123 §5). The rest is named from the person: the volumes
`hub-<person>-data` and `hub-<person>-keyring`, the container `hub-<person>` on a bridge
network of its own, also `hub-<person>`, and the unit `hub@<person>.service`, which the
deploy installs from `deploy/container/hub@.service`. That unit is this page's systemd
unit made real: the flags above, `docker run` in the foreground so its exit is the
container's, `Restart=on-failure`, `RestartPreventExitStatus=78`, a stop timeout of 120
seconds over Docker's 90, and a start at boot. A misconfigured gateway exits `78` through
the container (#3167), so it too stays down until someone acts. `journalctl --unit
hub@alice` is the container's log.

The image is built on the box, from a context `deploy/container/build.sh --context`
stages here out of a clean tree, and is labelled with its commit; nothing is pushed to
or pulled from a registry but the base images. `--image <ref>` deploys an image already
on the box instead, if it carries that label. Never prune the image a person's unit
runs: the next deploy backs up with it.

Before it stops anything, the deploy also checks what ADR-0327 §5:2 asks of the box,
that no other machine reaches the hosted listener. It checks that `route_localnet` is
`0` for every interface but the loopback and Docker's own, so nothing routes a packet
for the loopback port in from another machine. Once the container runs, it checks that
the container is on its own bridge network, publishes `8423` to `127.0.0.1` alone and
has no IPv6 address, and that the raw table's `PREROUTING` chain drops what arrives for
the container's bridge address, at the hosted port, on any other interface. Docker
Engine 28 and later write that rule for each published port, on the iptables backend.
A box where it cannot establish one of these is refused, or its container stopped, with
the reason. What it cannot see is a firewall
other than iptables, the network beyond the box, and a process on the box that forwards
the port itself.

It is ready when its health check passes:

```bash
docker inspect --format '{{.State.Health.Status}}' hub-alice   # healthy
docker logs hub-alice
```

The log carries the hub's and the gateway's own lines, and the supervisor's, which
start `hub-container:`. The last of those at start is `ready: the gateway's hosted
listener accepts on <address>:8423`. The gateway also prints the bootstrap value for
its loopback listener, as first-run.md describes; inside a container nothing reaches
that listener, and nothing needs the value.

## 4. Check the door

A request from the box's loopback without the edge's assertion is refused:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: alice.example.com' http://127.0.0.1:8501/
# 403
```

A `403` is the gateway answering. Anything else — a refused connection, a timeout —
means the request never reached it. Point the edge at `127.0.0.1:8501` for this
person, and the signed requests it forwards are served.

The published port is one way to the listener. The other is the container's own
address on the bridge network, which every process on the box can reach as it can
the loopback port — the edge's signature, not the address, is what stands between
them and the door (ADR-0327 §6). What no other machine may do is reach either
(§5:2): the box must not route traffic from elsewhere into its bridge networks, and
its firewall should admit nothing but what it serves. Check it from another machine
before the first person is invited.

## 5. The setup acts

Every act at the hub runs inside the container with `docker exec`, as the
container's own user and in its working directory, so it reads the same settings
and reaches the same keyring. Never pass `-u root` or `-w`: the hub admits acts
only from its own user, and the settings it shares with them are in that directory.

The operator performs these only at the person's request, and never one that
carries the person's authority (the #879 ruling):

```bash
# The devices the hub knows, before choosing ASSISTANT_GATEWAY_HOSTED_DEVICE.
docker exec hub-alice ai-assistant-device list

# The hosted browser device does nothing until it holds a role (ADR-0327 §10). It
# exists only once the gateway has named it, on the first request it relays: have
# the person sign in through the edge once, check that `list` shows alice-web, and
# only then give it the role.
docker exec hub-alice ai-assistant-device assign alice-web commands

# A connection's credential goes to the keyring, read from standard input.
printf '%s' "$CREDENTIAL" | docker exec -i hub-alice assistant connect brave-search --credential-stdin
```

`assistant connect` and the commands like it take the same arguments they take
outside a container; `docker exec hub-alice assistant --help` lists them.

## What the container's exit means

A program inside it, `supervise.py`, starts the bus, the keyring, the hub and then
the gateway, in that order and each only once the one before it is up. It restarts
nothing: its exit is the container's, and it uses the hub's three codes (ADR-0083
§5).

| Exit | Meaning | The supervisor outside should |
| --- | --- | --- |
| `0` | A stop was asked for, and the hub drained. | Not restart. |
| `1` | Something stopped that should come back: the hub crashed, the keyring stopped, or the gateway stopped, before the container was ready or after. | Restart. |
| `78` | The deployment is wrong, and restarting changes nothing until someone acts. The cause and the action are the last lines of the log. | Not restart. |

A stop is `docker stop`. It sends the gateway `SIGINT` and the hub `SIGTERM`
together and waits for both; a second stop changes nothing.

**Docker's restart policies cannot leave a `78` down.** `on-failure` restarts it,
and so do `always` and `unless-stopped`, so a deployment fault becomes a restart
loop, the failure ADR-0083 §5 exists to prevent. The supervisor outside should
instead be one that can tell the codes apart. systemd is the reference ADR-0083
names; a unit of this shape runs one person's container, illustrative only:

```ini
[Unit]
Description=Hub container for alice
After=docker.service
Requires=docker.service

[Service]
ExecStartPre=-/usr/bin/docker rm --force hub-alice
ExecStart=/usr/bin/docker run --rm --name hub-alice ...the flags from step 3, without --detach...
ExecStop=/usr/bin/docker stop --time 90 hub-alice
Restart=on-failure
RestartPreventExitStatus=78
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
```

`docker run` without `--detach` exits with the container's code, which is what lets
`RestartPreventExitStatus=78` read it.

## Upgrading

Run the deploy again. An upgrade is a cutover (ADR-0326 §2:6), and the deploy does it in
this order:

1. **Everything it can refuse, while the hub still serves.** The person's files and their
   modes, the volumes, the image the unit runs now, the port, the box's routing; then the
   new image is built and the unit installed. A refusal ends with `Nothing has been
   stopped or changed.`
2. **The backup, before the new image runs** (§6:1). The unit is stopped, and the image
   that wrote the data runs its own `ai-assistant-backup` over the data volume, in a
   container with no network, to `backups/pre-deploy-<UTC>-<run>.age`. A backup that
   fails, or is written but unverified, leaves `unit.env` as it was and starts the unit
   again: the earlier image runs, and the new one never has (§6:2).
3. **The new image**, named in `unit.env` and started on the same volumes (§3:1). The
   hub upgrades its stores as it opens them (§4).
4. **The checks.** The container is healthy and runs the new image, the door answers
   `403` without the edge's assertion, and the reachability checks of step 3 pass.

Once the new image has run, the deploy never starts the earlier one on that data, because
an earlier build cannot open a directory a later one upgraded (§5:4). A new image that
does not become healthy is left to its unit only where the reachability checks pass;
otherwise, and whenever the door or those checks fail, the deploy stops it, and says so
plainly if it cannot. Undoing the deploy is a later image, or the backup restored into a
new volume. The
artifact is kept; the deploy deletes none, and pruning old ones is the operator's act.

The backup copies the data volume as the image pins it, `/data`, with the exclusions the
tool makes and no others (ADR-0123 §3, ADR-0314 §7:5). It runs with the image's own
settings and not `hub.env`, because the data directory and every exclusion follow from
`/data` alone. One deploy per person runs at a time: a second refuses while
`/srv/hubs/<person>/.deploy-lock` exists, and a deploy killed outright leaves it for
you to remove.

## When it does not work

Every refusal ends with `(exit 78)` on a `hub-container:` line, or with the hub's own
`hub: cannot start:` lines above it.

| The log says | What to change |
| --- | --- |
| `no keyring passphrase is mounted at /run/secrets/keyring-passphrase` | Mount the passphrase file there. |
| `the keyring passphrase at … cannot be read` | Give the file to uid 10001. |
| `nothing is mounted at /data` or `at /home/assistant/.local/share/keyrings` | Mount the person's volume there. |
| `ASSISTANT_DATA_DIR is …, but the data volume is mounted at /data` | Remove `ASSISTANT_DATA_DIR` from the env file. |
| `… configured. In this container the gateway reaches the hub over the local socket` | Remove the remote settings it names from the env file. |
| `the container holds 2 besides loopback` (or any count but 1) | Run it on a bridge network, not `--network host`. |
| `ASSISTANT_GATEWAY_HOSTED_ADDRESS=127.0.0.1 is a loopback address`, or `… is set but blank` | Remove it from the env file. |
| `the passphrase at … does not unlock the login keyring` | Mount the passphrase this keyring volume was created with. |
| `the gateway refused to start before its hosted listener accepted` (exit 78), or `the gateway exited 1 before its hosted listener accepted` (exit 1, so it is started again) | Read the gateway's own message above it. A `78` names what to change, and the container stays down until you change it; a `1` is a fault that may clear, so the container is started again. |
| `hub: cannot start: … holds no credential` | Put the model key in the env file. |

## What this page is not

- **Provisioning a person from an invite**, which writes the person directory the
  deploy reads, and **installing a container runtime on the box**: both are the
  private operations repository's.
- **A deploy with Podman, or with Docker's nftables firewall.** The deploy path runs
  `docker` under systemd, and reads the iptables rules Docker writes.
- **The sign-in edge.** This page assumes one, and configures the gateway to check
  what it signs.

The image is proven by the `container` workflow on GitHub's runners, which builds
it and drives every step above on a fresh volume: readiness, the door, the setup
acts, a restart and a replacement carrying the data, a clean stop, and each
refusal. Its `deploy` job proves the deploy path the same way, with the runner as the
box: a first install, an upgrade that backs up and carries the data, a failed backup
that leaves the earlier image running, and the unit restarting a killed container and
leaving a `78` down. It is built with Docker; `CONTAINER_RUNTIME=podman just
container-image` builds the same file, and nothing on this page is proven with Podman.
