# Hosted family hubs

**The question.** May this system run a hub for someone other than the person who
runs the machine it is on, starting with a pilot of two to five close family members,
and if so, on what terms?

Today the answer is no. Each person runs their own hub on a machine they operate. This
proposal asks for a yes, for the pilot, under terms the project's owner ruled in
conversation on 2026-10-17. It does not decide how a hosted person reaches their hub's
web page. That is the door, and it gets its own proposal.

## Why now

- **The pilot needs it.** The first users are close family. A hub on their own machine
  means about thirteen commands and two open terminals by the 2026-10-17 survey's count,
  plus an always-on machine. [#3112](https://github.com/leonapivato/ai-assistant/issues/3112)
  records the install guide's known errors on top of that.
  None of them will do that. The owner wants to host their hubs instead.
- **A hosted hub can already be reached.** Milestone 12's Telegram line (ADR-0323) has
  the hub call out to Telegram by long polling. It needs no public address and no
  listener anyone else can reach. A hosted family member can talk to their assistant
  through their own bot the day their hub starts, with no web door at all.
- **The incumbents host.** Muse and Dots each give a user a cloud computer. A pilot that
  asks family to run a server tests the wrong thing.

## The baseline

These would read differently afterwards.

- **The wiki's [Hub](https://github.com/leonapivato/ai-assistant/wiki/Hub/c0d545777763afff0278b810202b56dc7ed940bc)
  page** (revision `c0d5457`, read 2026-10-17). It says "One running hub owns one data
  directory" and "The assistant's durable records remain in the hub's data directory".
  Both stay true. The page says nothing about whose machine the hub runs on, or who
  operates it.
- **Roadmap stance 6** (`docs/roadmap.md`, tracked by
  [#879](https://github.com/leonapivato/ai-assistant/issues/879)). "A **VPS is ruled
  out**: a host that roots the store is the maximal ADR-0017 §1 decision, and it sits
  against the trust thesis rather than merely costing something." The owner's own hub has run on a rented Hetzner box since
  2026-08-21, as a temporary exception the owner ruled and #879 records.
- **ADR-0004 §2's residency clause**, "All persistent data lives on the user's
  machine", which **ADR-0155 §1:1** reads as governing the assistant's own store: "That
  store lives on the owner's machine, under that one directory, and no component of
  this system places any part of it in a service another party operates". The
  temporary exception passed this clause because the owner operates that box. A family
  member's hub would not pass it, because the operator is someone else.
- **ADR-0323 §12**, the narrow precedent. The owner ruled (2026-10-17,
  [#2819](https://github.com/leonapivato/ai-assistant/issues/2819)) that the Telegram
  line may carry covered content to the owner's one chat, which Telegram keeps on its
  servers. That ruling covers the line's calls to that one chat and nothing wider, so
  it does not reach hosting. What it shows is the form a scoped exception to ADR-0155
  takes: named, bounded, with its privacy cost stated (ADR-0323 §14).
- **The acts ADRs place "at the hub".** Enrolling a device is "an act the owner
  performs at the hub" (ADR-0124 §6). A credential reaches a connection only over the
  hub's loopback socket (ADR-0151 §13's third clause). The Telegram line's approval is
  "two acts, both the owner's" (ADR-0323 §12). Each assumes the owner has a shell on
  the hub's machine. A hosted family member does not.
- **Fresh data directories at cutovers.** The live hub has started on a fresh data
  directory at each large cutover (`data-m38`, `data-m39`, `data-0283`, `data-step3`,
  `data-m41`, `data-m44`), and ADR-0309 §6:1 and §6:4 made that the rule for the M44
  cutover. That is a practice, not a standing ADR. For a hosted person it means their
  assistant forgets them.

## The change

### Two roles where there was one

A hub keeps **one owner**: the person it serves, whose user model it holds and whose
yes authorises what it does. That does not change, and nothing here makes a hub serve
two people. ADR-0124 §10's "Nothing here authorises a second hub" still holds: every
hosted person has their own hub, and each hub has one owner.

What is new is naming a second role the corpus has never needed: the **operator**, who
runs the machine. The operator has root, deploys, takes backups and restarts units. On
a self-run hub the owner is the operator, which is why the corpus could say "the owner"
for both. On a hosted hub they are different people, and the proposal uses the two
words apart from here on.

### The residency clause, for a hosted hub

ADR-0155 §1:1 would be superseded for a **hosted hub**: one whose owner has asked an
operator they chose to run it for them, and has been given the pilot's terms. Its store
lives on the operator's machine, under one data directory, as now. Everything else in
ADR-0155 stands, and so does ADR-0323 §12's line exception. Nothing in this system
places any part of the store anywhere else.

That is a supersession, not a reading. "The owner's machine" does not stretch to cover
someone else's box, and stretching the words would hide the decision. The supersession
is the decision, and stating it in the open is the point.

### Stance 6

The stance becomes: a hub may run on a rented box when its owner chooses that, either
as their own operator or with an operator they trust. That covers the owner's own hub
(the 2026-08-21 exception stops being an exception) and the family's. The trust thesis
moves from "nobody else's machine" to "a machine run by someone you chose, on terms you
were told". That matches the owner's view that what withholding protects against is
other people, not providers.

### The pilot's terms

Ruled by the owner on 2026-10-17:

- **Storage is plain; trust is by relationship.** The operator can technically read any
  hosted store. The operator commits not to look, except when the owner asks for help
  with something that needs it. No encryption at rest is added. Backups are encrypted
  already: `ai-assistant-backup` (ADR-0123) encrypts the whole data directory to a
  passphrase, which the operator holds for each hosted hub.
- **Resets happen with notice.** A cutover may start a hosted hub on a fresh data
  directory, as the practice is today. The owner is told beforehand through their line.
  The previous directory is kept for a while, then removed (how long is open, below).
  Each reset restarts that person's learning loop, which is the pilot's cost for keeping
  cutovers cheap. Revisit before any launch.
- **Model spend has no cap; the operator is alerted.** Each hosted hub has its own
  provider key in its own workspace. That shows spend per person and puts the alert in
  the provider's console, with nothing to build.
- **Size and place.** Up to five hosted hubs plus the operator's own, on one box in a US
  region. The family is in the US. About 450 MB of memory per idle hub (measured on the
  live hub, 2026-10-17) puts that at about 8 GB.
- **Leaving.** On the owner's request, the operator stops the hub, hands over a backup
  with its passphrase if the owner wants one, and deletes the data directory and every
  backup of it.
- **Telling them.** Before a hosted hub starts, the owner gets a one-page note in plain
  words: who can see their data, what Telegram and the model provider keep, that resets
  happen, and how to leave.

### The box

```mermaid
flowchart LR
    subgraph BOX["The operator's box (US region)"]
        direction TB
        subgraph U1["Linux user: one per hosted owner"]
            H1["hub"] --- K1["keyring"]
            H1 --- D1[("data directory, 0700")]
        end
        subgraph U0["Linux user: the operator's own hub"]
            H0["hub"] --- K0["keyring"]
            H0 --- D0[("data directory")]
        end
    end
    H1 -- "long poll, calls out" --> TG["Telegram: the owner's own bot"]
    H1 -- "calls out" --> MP["Model provider: this hub's own key"]
    OP["Operator"] -- "ssh, root" --> BOX
    PC["Operator's devices"] -- "tailnet, ADR-0124" --> H0
```

- **One Linux user per hub.** It has its own lingering systemd user units (the hub and
  a headless keyring, as the live `assistant` user has now), its own data directory,
  `hub.env`, venv and provider key. The hub already creates its data directory
  owner-only (`service/datadir.py`, `_OWNER_ONLY_DIR`), so one hub's process cannot
  read another's store. Root can read them all, which is the plain-storage term above.
- **A hosted hub binds only its loopback socket.** It sets no remote listener, so it is
  on no overlay, and ADR-0124 §2 has nothing to reach. Its owner reaches it through
  lines that call out, Telegram first, and later through the door. The operator's own
  hub keeps its tailnet listener for the operator's devices, unchanged.
- **Deploys go through `scripts/deploy_hub.py` once per hub.** It already takes the
  ssh user, unit, venv, uv binary and marker as arguments. Whether it needs anything
  more for several hubs on one box is for the implementation lane to find out.

### Acts at the hub, for a hosted owner

A hosted owner has no shell. So for them, the operator performs the acts the corpus
places at the hub: connecting the owner's bot and setting `telegram_user_id`
(ADR-0323 §3), enrolling, assigning roles and listing devices, and connecting any
account. The rule proposed: **the operator performs an owner's at-the-hub act only at
that owner's request, the act is recorded as it is today, and it counts as the
owner's.** For the Telegram line, the owner creates their own bot with the operator
beside them, and the operator enters its token at the hub.

## Options considered

- **Each person runs their own hub (today).** It needs no ruling, and nobody in the
  pilot would do it.
- **One multi-user hub.** Rejected. A hub has one owner all the way down: one data
  directory (ADR-0083), one user model, one yes. Making a hub multi-tenant would
  rewrite all of that for a worse isolation story than separate processes.
- **A container per hub instead of a Linux user.** Cleaner isolation and the likely
  shape at launch. For five people it is new build work, an image and a runtime, with
  nothing to show for it yet. A Linux user per hub reuses the live deployment as it
  stands. Recommended for the pilot, revisited at launch.
- **Encryption at rest, or a key the owner holds.** The owner ruled plain storage for
  the pilot. A key the owner holds is weak anyway for a hub that runs all the time: the
  key sits in memory, and real protection needs a confidential VM.
- **Migrations instead of resets.** The owner ruled resets with notice for the pilot.
  Carrying memory across cutovers is the launch's job, and possibly an export and
  re-import that doubles as history import.

## What it leaves open

- **The door.** How a hosted owner signs in to their hub's web page. That is the next
  proposal: Cloudflare Tunnel plus Cloudflare Access (the owner's ruling, 2026-10-17),
  with a gateway listener that checks Access's signed token. It would supersede
  ADR-0168 §2's proxy clause and extend ADR-0174. The domain is an operating detail of
  that proposal.
- **The dedicated box (#879).** Whether the "dedicated always-on machine" direction
  survives once a rented box is a standing choice, or #879 closes as not planned.
- **Moving the operator's own hub.** Whether it moves from the Hetzner box in Nuremberg
  to the US box, by copying `data-m44` or by starting fresh.
- **How long a reset keeps the previous directory**, before it is removed.
- **The exact ADR text for "the operator acts for the owner"**, and which existing
  clauses it touches by name (ADR-0124 §6, ADR-0151 §13, ADR-0323 §12).
- **Launch terms.** Encryption, migrations, containers, accounts and payments. These
  pilot terms decide none of them.
