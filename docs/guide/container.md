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

# The hosted browser device does nothing until it holds a role (ADR-0327 §10).
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
| `1` | Something stopped that should come back: the hub crashed, the gateway or the keyring stopped after the container was ready, or a signal ended the gateway before it was. | Restart. |
| `78` | The deployment is wrong, and restarting changes nothing until someone acts — the gateway exiting on its own before its listener ever accepted among it. The cause and the action are the last lines of the log. | Not restart. |

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

Build the new image, stop the container, remove it, and run the command from step 3
with the new tag. The volumes carry the data directory and the keyring across, and
the hub upgrades its stores as it opens them (ADR-0326 §4).

ADR-0326 §6 requires a deploy to a person's hub to take a verified backup of the
data directory before it installs. The container deploy path that does that is not
built yet; it is #3160. Until it is, take that backup with the container
stopped, before you remove it.

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
| `the gateway exited 1 before its hosted listener accepted` | Read the gateway's own message just above it: usually an edge setting. |
| `hub: cannot start: … holds no credential` | Put the model key in the env file. |

## What this page is not

- **The deploy path.** Building, backing up, replacing and verifying a person's
  container as one act is #3160.
- **Provisioning a person from an invite**, and **installing a container runtime
  on the box**: both are the private operations repository's.
- **The sign-in edge.** This page assumes one, and configures the gateway to check
  what it signs.

The image is proven by the `container` workflow on GitHub's runners, which builds
it and drives every step above on a fresh volume: readiness, the door, the setup
acts, a restart and a replacement carrying the data, a clean stop, and each
refusal. It is built with Docker; `CONTAINER_RUNTIME=podman just container-image`
builds the same file, and nothing on this page is proven with Podman.
