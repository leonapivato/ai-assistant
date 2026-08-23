# Install

You end this page with nine commands on your `PATH` and nothing running yet.

## 1. Get uv

[uv](https://docs.astral.sh/uv/) is this project's packaging tool, and getting
it first is what keeps the rest of this page short: **uv chooses the Python
interpreter for every command below**, so you never have to name one, find one,
or get its directory onto your `PATH`.

Install it the way [uv's own documentation](https://docs.astral.sh/uv/getting-started/installation/)
says to for your platform — its standalone installer needs neither Python nor
pip, and every major package manager also carries it. Then check:

```bash
uv --version
```

```text
uv 0.12.5 (x86_64-unknown-linux-gnu)
```

If you installed it with `pip` into a particular interpreter and that
interpreter's script directory is not on your `PATH`, `uv` will not be found —
`<that python> -m uv` reaches exactly the same program, and works everywhere
`uv` does. Substitute it in every `uv` command below if that is your situation.

## 2. Get the wheel

There is no published release yet: you build the wheel from a source checkout,
once, and then install the file it produces. That needs **git**, which is the
one prerequisite uv cannot supply — take it from your platform's packages
(`apt install git`, `brew install git`).

```bash
git clone https://github.com/leonapivato/ai-assistant.git
cd ai-assistant
uv build
```

`pyproject.toml` declares `requires-python = ">=3.14"` and the checkout pins
3.14 in `.python-version`, so uv resolves an interpreter that satisfies both.
If you would rather have one under your own hand — the pip route in step 3 needs
a real 3.14 executable — `uv python install 3.14` installs it and
`uv python find 3.14` prints the path to it.

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

**With pip**, into a virtual environment you make yourself. This is the one
route that needs a 3.14 executable by name — write the path
`uv python find 3.14` printed, or your own `python3.14`:

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
before downloading anything. You hit this only on the pip route, because it is
the only one where you choose the interpreter: point it at a 3.14, or use the
`uv tool install` route, which chooses one itself.

**`assistant: command not found` after `uv tool install`** — uv installs the
commands into `~/.local/bin`, which is on your `PATH` only if something put it
there. `uv tool update-shell` adds it; open a new shell
afterwards. Or call them by their full path, which is what the
`~/.venvs/assistant/bin/` route above amounts to.

Next: [`first-run.md`](first-run.md).
