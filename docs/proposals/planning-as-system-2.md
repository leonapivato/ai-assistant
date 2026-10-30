# Planning as deliberate thought

**The question.** What is planning responsible for, and what has to change around
it so that its instruction says only that?

## The idea

Planning is the system's deliberate thought, its System 2 (the owner's framing,
2026-10-28). It works out the goal a stimulus calls for, thinks through how to
reach it, decides how the system responds, and sees that through until the goal
is met. Understanding and recall are the path that feeds it; they never respond.
There is no System 1 yet, and planning is designed as System 2 alone, with no
rules standing in for one.

Everything that is not deliberation moves out of planning:

- delivery goes to code;
- permission stays with authorizing;
- incidental memory goes to the observer;
- a rule about one tool goes into that tool's description;
- style goes into the person's preferences, as data.

What remains in planning's instruction is what applies to every stimulus. It was
drafted with the owner, is much shorter than today's, and ships with the
implementation. Its text is kept off GitHub until then.

## The baseline

- **Wiki**, read at revision `84f20c8`:
  - [Planning](https://github.com/leonapivato/ai-assistant/wiki/Planning): "What a round holds", "Rounds" and "Rules".
  - [Planner inputs](https://github.com/leonapivato/ai-assistant/wiki/Planner-inputs): "What changes on a later round".
  - [Episodes](https://github.com/leonapivato/ai-assistant/wiki/Episodes).
  - [Stories](https://github.com/leonapivato/ai-assistant/wiki/Stories).
- **ADRs whose clauses this would touch:**
  - **ADR-0307:** a round is one response that writes its own message and keeps episode notes; each round is asked afresh; what planning is shown; its look-ups.
  - **ADR-0315:** a round that made a call brings another round.
  - **ADR-0306:** what a capability declares about its calls.
  - **ADR-0300 and ADR-0303:** planning's story calls.
  - **ADR-0329:** planning records candidates for the observer.
  - **ADR-0334:** a prompt is a template with flags.
  - **ADR-0338:** the lines planning's instruction must carry about the person block.
  - **ADR-0350:** a scheduled task's message names its place.
  - **ADR-0352:** answering an offer.
  - **ADR-0353:** understanding's tagged input, the model for planning's.
  - **ADR-0355:** thinking summaries kept as diagnostics.

## The change

### 1. Planning's context is tagged text

Planning is shown its context the way understanding is since ADR-0353:
- the stimulus;
- then the system's understanding of it;
- then knowledge: the situation, the stimulus origin's own records, concurrent stimuli;
- then memory: always in mind, short-term, long-term, and the origin's memory.

Every item is wrapped in a tag that says who or what it is from. Planning is told
its context is only part of what the system knows, and that it can look up more.

### 2. No switches, and a stable core of tools

Every section is always present, and an empty one says why. That is the rule
ADR-0353 gave understanding.

A core of tools is offered on every round, the same set each time:
- the message tools;
- the look-ups;
- answering an offer;
- remembering;
- reminders.

A core tool called with nothing to act on comes back saying why, for example
"no offer is open". Two reasons:
- **Caching.** The tools head the cached prefix, so a tool set that varies from
  round to round breaks the cache every time.
- **Planning's `$if` flags go,** and with them the conditional parts of its
  template.

Tools beyond the core are not switched in and out by round. Today almost every
tool is core. As integrations grow, the rest are reached through memory: recall
brings them to mind, or planning searches for them (see "Direction"). They are
called through one fixed `use_tool(name, arguments)`, so the offered set never
changes.

### 3. One continuing exchange

Today each round is asked afresh: the whole context is rendered again, and no
earlier turn is replayed. Instead, each round's turn, its calls and their results
are appended to one exchange. Anything that changed since the last round arrives
as news in the next turn, so the view stays current without a full re-render.

The request is ordered for caching:
1. the instruction;
2. the stable context;
3. what changes.

Planning keeps sight of its own earlier rounds, and the context is no longer
re-read in full each round. Whether a model also keeps its earlier reasoning
depends on the model, and nothing relies on it.

### 4. Saying something is a call

The people the system works for see only what planning's calls do, never its
text (see change 6). A round with no calls ends the work. Messages are tools,
split by modality the way people think of them:

| Tool | What it is |
| --- | --- |
| `text` | A short written message. iMessage, WhatsApp, Telegram and the hub chat are the same action, and code picks the platform. |
| `email` | Subject, attachments, slower and more formal. |
| `speak` | Voice, when that interface exists. |

- **Whose voice.** `text` and `speak` are always in the system's own voice.
  `email` may be sent from the system's address or from the person's, and the
  person's address is gated.
- **A person, not an address.** Each tool takes a person, and code resolves how
  to reach them. A person it cannot tell apart from another comes back asking which.
- **Exact words.** Each tool can send its words exactly as written.
- **The result.** Each tool's result returns what was actually delivered, where
  it went, and whether it was sent, delivered, read, failed or unknown, with the
  reason.

So a message can wait for the results it reports. The rule that a message never
claims how its own round's calls went becomes general: a call that needs
another's result, or tells of it, goes in a later round.

Every message brings one more round, which sees how the message went and ends
the work. With caching, that round costs little.

### 5. Act, or come back with what's needed

This is one rule for every tool.
- **When the tool can resolve the details itself,** it acts and reports what it did.
- **When it cannot, it does not act.** It returns why, and what is needed to call
  it again: the valid options, or the live facts. This covers an argument that is
  missing or wrong (never guessed), a choice with no way to decide it, a condition
  that failed, a call that needs a yes, and a person who can't be reached.
- **Planning can state conditions in the call,** such as "only if she's alone".
  Without one, the tool takes the safe default, which for speech means coming back
  when others are present.
- **A tool with effects checks its own record and does not repeat an action**
  already done. It comes back saying so. Each tool's description says whether it
  is safe to repeat.

### 6. Planning's text is its own notes

The tool that carries episode notes goes. Any text planning writes outside a
call is its notes:
- its later rounds see the notes, since the exchange keeps them;
- later work sees the work's last note, in the episode's short view;
- nobody else does.

The people the system works for see only what the calls do. The instruction says
so plainly.

Text needs no tool, so this reuses the habit models already have of writing text.
And text in the exchange survives from round to round on every provider, where a
model's own thinking may not.

**The risk:** a model trained to answer users in text may write its reply as a
note and call no message tool, and the person then gets nothing. The first suite
case for this design checks it: a plain question must come back as a message
call.

### 7. What an episode shows

Short-term memory and recall show an episode's **short view**. It is a selection
of the episode's own recorded parts, made by code, never a summary:
- the input;
- the meaning understanding recorded;
- the messages as sent;
- what was done: each call with an effect, with its outcome;
- the work's last note;
- how it ended.

Today's view shows no calls and no outcomes. So a later stimulus cannot tell
whether an email was already sent, unless a message happened to say so.

A new **episode look-up**, like reading a story, gives the full record. It is
filtered by the reader's audience, removes memories since forgotten, and keeps
outside content withheld.

Raw thinking is never shown outside its own work. ADR-0355's summaries stay in
the diagnostic record. Planning's notes are the thinking it chooses to keep.

### 8. Memory planning keeps only on purpose

What is worth keeping from a piece of work is gathered by the observer after it
ends.
- **`remember`.** Planning calls it only when someone asks, or when the work
  needs something kept now. It stays a candidate: the observer decides whether to
  keep it, weighing what is already held and where the fact came from.
- **Confirming.** "I'll remember" is true at the system level, so the old rule
  against saying "saved" goes.
- **Matter notes.** Planning still notes on a matter what the matter needs now.
- **Reorganising matters.** Planning still reorganises a matter when asked.
  Reorganisation nobody asked for goes to the observer.

### 9. Rules beside their tools

The instruction carries only what applies to every stimulus. Each of these moves
into its tool's description:
- when to take or decline an offer;
- reminders, including snoozes and skips;
- when to start, note or link a matter;
- when to remember;
- noting the memories relied on;
- how messages behave;
- that the system never claims to be human, which moves into the message tools.

### 10. Default preferences, as data

How much detail to give, whether to confirm what was done, whether to report
what wasn't, whether to say which reading was taken, and everyday versus
technical words are all taste. Each person starts with a default set, held in
what the system always keeps in mind. They can change it, and so can the
observer.

The instruction sets no house style. What stays as rules is only what nobody
would want reversed:
- preferences never change what is true;
- never claim an outcome before it is known;
- never use a label outside the work.

### 11. Look-ups that are missing

For the instruction's "you can look up more" to be true, planning needs three
look-ups it lacks:
- past episodes beyond short-term memory;
- a matter it was not shown;
- the origin's older history.

### 12. ADR-0338's instruction lines

ADR-0338 requires planning's instruction to say three things:
- that a field outweighs a memory stating another value;
- to use what the person block holds;
- that no preference, pin or field changes what is true, what Aether judges best
  or any rule, and that Aether never claims to be human.

Under this proposal, preferences reach planning as data, which it weighs and is
never instructed by, and the last point moves into the message tools.

Those clauses would be amended alongside the change. Until then, any shipped
instruction still carries them.

## Options considered

- **Keep each round asked afresh.** It keeps the view current, and never
  replays tool turns in a provider's own form. But planning loses sight of its own
  rounds, and nothing is cached. Change 3 keeps the view current by sending
  changes as news.
- **One wide `say` tool,** with who, where and in whose name as arguments. The
  "whose name" argument changes the stakes, the permission and the style, which
  makes it a different act. Splitting by modality matches how people think, and
  lets planning write for the medium it chose.
- **A "final" flag on a message that ends the work.** It loses failures: a round
  holding a booking and a final "Booked!" ends even if the booking failed.
  Dropped for one cheap round after each message. A later option is a "last
  round" flag honoured only if every call of the round succeeds, with that round's
  messages sent only after its other calls succeed.
- **Show whole episodes.** It is large, it brings back memories forgotten since
  through old search results, and it shows stale results as if current. Change 7
  shows the short view, with a look-up for the rest.
- **Keep an explicit "remember this" for sure.** Declined by the owner: whether
  to keep it is the observer's call, which sees duplicates and provenance.
- **A scratchpad tool for notes:** a tool that runs nothing, each write holding
  the whole plan. It works, but it adds a tool for something text already does
  once rounds are appended. Change 6 uses text instead.
- **Offer every tool on every round.** It is simple while the tools are few, but
  it doesn't scale: models choose worse among dozens of tools, and each one costs
  tokens. Change 2 offers a stable core instead, and leaves the rest to memory.

## Direction, not proposed here

Each of these spans recall, memory and the observer, so each would be its own
design:
- **Tools and skills held in memory, beyond the core.** Recall brings to mind the
  tools and the know-how a stimulus calls for, the observer learns per-person
  procedures, and planning can deliberately search for a tool, as it searches for
  a fact. Tools found that way are called through `use_tool`. Skills give procedures that
  span several tools a home, so they never return to the instruction.
- **Intentions tied to an event, not a time.**
- **Lessons from corrections.**
- **The system's own promises, kept as obligations.**
- **A System 1 pathway.**
- **A wording phase** that renders planning's content for its medium.
- **For `speak`: presence, and the question of private content.** Who is around
  belongs in the situation. Whether code should refuse to speak private content
  when others are present is a question for the audience and privacy work.

## What it leaves open

- **The exact tagged shape of planning's context.** A mock with invented data
  comes next, as it did for understanding.
- **How "what was done" renders for each tool.**
- **The round limit, and caching details for each provider.**
- **Whose side planning takes in a household,** when one person's stimulus
  affects another. It is deferred while the owner holds full control.
- **How the change splits into ADRs.** A suggestion:
  - one for the exchange: changes 1–7, with ADR-0338's amendment;
  - one for memory: changes 8, 10 and 11;
  - one for the tools: changes 4, 5 and 9.

  The instruction would ship with the first one's implementation, as
  understanding's did with its renderer.
