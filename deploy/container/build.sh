#!/usr/bin/env bash
# Build the container image for one person's hub and its gateway (#3142).
#
#   deploy/container/build.sh [TAG]
#
# TAG defaults to ai-assistant-hub:<the commit's first twelve characters>. The runtime
# is `docker`, or whatever CONTAINER_RUNTIME names (`podman` builds the same file).
#
# What goes into the image is what `scripts/deploy_hub.py` installs on the box:
#
# - a wheel built from a clean tree, so the commit the image is labelled with is the
#   commit it contains (ADR-0326 §2:4's release, §3:2's clean tree). Untracked files
#   count as dirt, as they do for deploy_hub;
# - `uv.lock`'s runtime set, exported pinned and hashed by the same command deploy_hub
#   runs (`uv export --locked --offline --no-dev --no-emit-project`, #3114), and
#   installed with no resolution, so the image's dependencies are the lockfile's and
#   never a fresh index resolve.
#
# The build context is a fresh directory holding those two files, supervise.py and
# session-bus.conf, and nothing else: no `.env`, no key and no passphrase can reach a
# layer by accident.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(git -C "$here" rev-parse --show-toplevel)"
runtime="${CONTAINER_RUNTIME:-docker}"

if [[ -n "$(git -C "$repo" status --porcelain)" ]]; then
    echo "build: the working tree has uncommitted or untracked changes, so the image" >&2
    echo "build: would not be the commit it is labelled with. Commit or stash first." >&2
    exit 1
fi
commit="$(git -C "$repo" rev-parse HEAD)"
tag="${1:-ai-assistant-hub:${commit:0:12}}"

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT

echo "build: wheel from $commit"
(cd "$repo" && uv build --wheel --out-dir "$stage/dist")
shopt -s nullglob
wheels=("$stage"/dist/*.whl)
if [[ ${#wheels[@]} -ne 1 ]]; then
    echo "build: expected one wheel from uv build, found ${#wheels[@]}" >&2
    exit 1
fi
mv "${wheels[0]}" "$stage/"

echo "build: uv.lock's runtime set"
(cd "$repo" && uv export --locked --offline --no-dev --no-emit-project --quiet \
    --output-file "$stage/requirements.txt")
cp "$here/supervise.py" "$here/session-bus.conf" "$stage/"

echo "build: $tag"
"$runtime" build \
    --file "$here/Dockerfile" \
    --label "org.opencontainers.image.revision=$commit" \
    --label "org.opencontainers.image.source=https://github.com/leonapivato/ai-assistant" \
    --tag "$tag" \
    "$stage"
echo "build: built $tag from $commit"
