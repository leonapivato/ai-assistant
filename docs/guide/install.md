# Install

You end this page with nine commands on your `PATH` and nothing running yet.

## 1. Check your Python

```bash
python3 --version
```

It must report **3.14 or newer**. The package declares `requires-python =
">=3.14"`, so an older interpreter refuses the install rather than half-doing
it. If yours is older, install 3.14 — [uv](https://docs.astral.sh/uv/) will do
it for you (`uv python install 3.14`), as will pyenv or your platform's
packages.

## 2. Get the wheel

There is no published release yet. You build the wheel from a source checkout,
once, and then install the file it produces:

```bash
git clone https://github.com/leonapivato/ai-assistant.git
cd ai-assistant
uv build
```

That writes two files into `dist/`. The one you want is the wheel:

```text
dist/ai_assistant-0.1.0-py3-none-any.whl
```

It is around **63 MB**, which is larger than a wheel of this much Python has any
right to be. The size is a vendored embedding model: semantic memory retrieval
runs locally, on your machine, and the weights ship inside the distribution
rather than being downloaded on first use (ADR-0024). Nothing about the install
reaches out for a model later.

You can move that one file to whatever machine you are installing on. The
checkout is not needed after this step.

## 3. Install it

**With uv** — the recommended route, because it puts the commands on your `PATH`
in an environment of their own that cannot collide with anything else you have
installed:

```bash
uv tool install ./dist/ai_assistant-0.1.0-py3-none-any.whl
```

It ends by naming what it installed:

```text
Installed 9 executables: ai-assistant-backup, ai-assistant-device,
ai-assistant-hub, ai-assistant-measures, ai-assistant-purge,
ai-assistant-reembed, ai-assistant-restore, ai-assistant-store-health,
assistant
```

**With pip**, into a virtual environment you make yourself:

```bash
python3.14 -m venv ~/.venvs/assistant
~/.venvs/assistant/bin/pip install ./dist/ai_assistant-0.1.0-py3-none-any.whl
```

The same nine commands land in `~/.venvs/assistant/bin/`. Everything later in
this guide names them bare (`assistant`, `ai-assistant-hub`); if you took this
route, either activate the environment or spell out the path.

Expect a few minutes and around a gigabyte of disk. The dependency tree
includes an ONNX runtime, a tokenizer library and NumPy, and four of them are
pinned to exact versions on purpose — two installs of the same wheel must
produce the same vectors from the same weights.

## 4. Check it

```bash
assistant version
```

```text
ai-assistant 0.1.0
```

That command loads no configuration and reads no data directory, which is why
it is the right first check: it answers "is it installed" without also asking
"is it configured".

## What the nine commands are

Two of them are the ones this guide uses. The rest exist so that you never have
to reach into the data directory by hand, and you can ignore them until you
need one.

| Command | What it is |
| --- | --- |
| `ai-assistant-hub` | The resident process. Start it and leave it running. |
| `assistant` | The command-line client, and the `gateway` subcommand. |
| `ai-assistant-device` | Enrol, revoke and list the devices a hub admits — see [`remote-hub.md`](remote-hub.md). |
| `ai-assistant-backup` / `ai-assistant-restore` | Take and restore a backup of the data directory. |
| `ai-assistant-purge` | Delete an installation and everything in it. |
| `ai-assistant-reembed` | Re-embed stored memory after the embedding model changes. |
| `ai-assistant-measures` | An offline report over what the hub recorded. |
| `ai-assistant-store-health` | Check the stores in a data directory. |

They are separate commands rather than `assistant` subcommands for a structural
reason rather than a stylistic one: each of them touches the data directory or
the hub's own lock directly, and the client is not allowed to import the code
that owns those (ADR-0084 §6).

## When it does not work

**`ERROR: Package 'ai-assistant' requires a different Python: 3.12.13 not in
'>=3.14'`** — the interpreter running `pip` is older than 3.14, and it says so
before downloading anything. Point it at a 3.14 interpreter, or use `uv tool
install`, which selects a suitable one itself.

**`assistant: command not found` after `uv tool install`** — uv installs into
`~/.local/bin`, which is on your `PATH` only if something put it there. `uv tool
update-shell` adds it; open a new shell afterwards.

Next: [`first-run.md`](first-run.md).
