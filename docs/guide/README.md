# Running the assistant

This is the prose guide for someone standing the assistant up for the first
time. It assumes you did not build it, and it assumes nothing about this
repository being on your machine — the first page installs from a built wheel.

Read the pages in order. Each one ends where the next one starts.

| Page | What it gets you |
| --- | --- |
| [`install.md`](install.md) | Python 3.14, the wheel, and the nine commands it installs |
| [`first-run.md`](first-run.md) | A data directory, a model key, a running hub, and a browser you can ask things in |
| [`phone.md`](phone.md) | The same browser page on your phone, over your own overlay network |
| [`remote-hub.md`](remote-hub.md) | The hub on one machine and your laptop as a client of it |

`first-run.md` is the whole of what "it works" means. `phone.md` and
`remote-hub.md` are each optional and independent of each other: you can do
either, both, or neither.

## What you are installing

Three things run, and it is worth knowing which is which before you start,
because every instruction below is about one of them.

- **The hub** (`ai-assistant-hub`) is the resident process. It owns the data
  directory, holds every store in it, and is the only thing that talks to a
  language model. One hub per data directory.
- **A client** is anything that asks the hub to do something. `assistant ask`
  on the command line is one. The gateway is another.
- **The gateway** (`assistant gateway`) is a client that serves a web page to
  the browsers on its own machine. It speaks HTTP to browsers and the hub's own
  protocol to the hub. It is not a hub, holds no data, and starting one does not
  start a hub.

The hub does not start a client, and no client starts a hub. If the hub is not
running, a client says so plainly rather than quietly doing the work itself.

## What you need before you start

- A machine running Linux or macOS. Everything below was run on Linux.
- **Python 3.14 or newer.** The package requires it and will not install under
  an older one.
- **git** and **[uv](https://docs.astral.sh/uv/)**, to get a checkout and build
  the wheel from it — there is no published release yet. `install.md` names both
  and gets uv for you if you do not have it. Neither is needed on a machine you
  only *install* the finished wheel on.
- An API key for **Anthropic** or **OpenAI**. The assistant is model-agnostic
  and you pick the route at configuration time; those two are the vendors whose
  libraries ship in the distribution, so they are the two that work without
  installing anything else.
- About 1 GB of disk for the install. The wheel is large (it carries a
  vendored embedding model) and its dependency tree is larger.

You do **not** need this repository, a C compiler, a database server, a
container runtime, or a network service of any kind. Nothing here listens on a
public address, and nothing here is meant to.

## If something goes wrong

Each page ends with a "When it does not work" section listing the failures
that page can produce, with the message each one prints. The messages this
system produces are meant to be read: they say what happened, and what to
change.
