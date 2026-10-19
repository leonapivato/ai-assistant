# syntax=docker/dockerfile:1
#
# One person's hub and its gateway, as one unit (#3142). How to build it, run it and
# stop it is docs/guide/container.md; `just container-image` builds it.
#
# The build context is not the repository. deploy/container/build.sh stages a wheel
# built from a clean tree (ADR-0326 §2:4's release), `uv.lock`'s runtime set exported
# as pinned, hashed requirements (the set `scripts/deploy_hub.py` installs since
# #3114), and supervise.py, and builds from that directory alone. Nothing here
# resolves a dependency, and nothing here holds a secret: no provider key, no keyring
# passphrase and no backup passphrase is written into any layer.

ARG PYTHON_IMAGE=python:3.14.8-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.10@sha256:2bb3ebca0a796a155094a27773d290c4b074572e6107f171d88d086682fd2500

FROM ${UV_IMAGE} AS uv

# --- The environment: the locked set, then the wheel ------------------------------
FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
COPY requirements.txt /stage/requirements.txt
COPY *.whl /stage/
# The same two installs, in the same order, as deploy_hub's locked path: the exported
# set with no resolution (`--no-deps`, every line pinned and hashed), and only then
# the wheel, whose own requirements that set already satisfies.
RUN python -m venv --without-pip /opt/assistant/venv \
 && uv pip install --python /opt/assistant/venv/bin/python --no-deps --require-hashes \
        --compile-bytecode -r /stage/requirements.txt \
 && uv pip install --python /opt/assistant/venv/bin/python --no-deps \
        --compile-bytecode /stage/*.whl

# --- The image ---------------------------------------------------------------------
FROM ${PYTHON_IMAGE}

# A genuine SecretService keyring, the only kind ADR-0125 §7 lets the secret store
# use: a session bus and a headless gnome-keyring on it, as on the box. tini is PID 1,
# forwards the stop signal to supervise.py and reaps.
RUN apt-get update \
 && apt-get install --yes --no-install-recommends dbus-daemon dbus-bin gnome-keyring tini \
 && rm -rf /var/lib/apt/lists/* \
 && dbus-uuidgen --ensure

# One unprivileged user, the hub's, with a fixed uid so a bind-mounted volume or
# passphrase file can be given to it. The three directories are created owner-only:
# a named volume mounted on an empty one copies its owner and mode, which is what
# ADR-0084 §1's check on the data directory asks for.
RUN groupadd --gid 10001 assistant \
 && useradd --uid 10001 --gid 10001 --home-dir /home/assistant --create-home \
        --shell /usr/sbin/nologin assistant \
 && install --directory --owner=assistant --group=assistant --mode=0700 \
        /data /home/assistant/.local /home/assistant/.local/share \
        /home/assistant/.local/share/keyrings /run/assistant

COPY --from=build /opt/assistant/venv /opt/assistant/venv
COPY supervise.py session-bus.conf /opt/assistant/

# The data directory is the volume at /data, pinned here, and supervise.py refuses an
# env file that moves it (ADR-0326 §3:1). The bus has a fixed address, so a command
# `docker exec` starts reaches the same keyring the children do.
ENV PATH=/opt/assistant/venv/bin:$PATH \
    ASSISTANT_DATA_DIR=/data \
    HOME=/home/assistant \
    XDG_RUNTIME_DIR=/run/assistant \
    DBUS_SESSION_BUS_ADDRESS=unix:path=/run/assistant/bus \
    PYTHONUNBUFFERED=1

USER assistant
# Every process reads the `.env` supervise.py writes here, `docker exec`'s included.
WORKDIR /run/assistant

# No VOLUME: an anonymous volume would hide a data directory nobody mounted, and
# supervise.py refuses to start on one that is not a mount point.
#
# The hosted listener's port (ADR-0327 §5:5). Publish it to the host's loopback
# alone: `-p 127.0.0.1:<port>:8423`.
EXPOSE 8423

STOPSIGNAL SIGTERM
HEALTHCHECK --interval=60s --timeout=5s --start-period=10m --start-interval=2s \
    CMD ["test", "-e", "/run/assistant/ready"]

ENTRYPOINT ["/usr/bin/tini", "--", "/opt/assistant/venv/bin/python", "-I", "/opt/assistant/supervise.py"]
