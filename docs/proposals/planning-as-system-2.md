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

The model expects someone to be talking to it in the `user` turn, so the framing
names that speaker: the system briefs planning.
- The context is the system's briefing.
- Results and news are the system reporting back.
- A person's words arrive inside that briefing, tagged as theirs, never as the
  briefer's.

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

Speaking to anyone is a call. Planning's text is meant for the system, as its
notes (see change 6), and what people receive comes only from the calls. A round
with no calls ends the work. Messages are tools, split by modality the
way people think of them:

| Tool | What it is |
| --- | --- |
| `text` | A short written message. iMessage, WhatsApp, Telegram and the hub chat are the same action, with the platform an argument. |
| `email` | Subject, attachments, slower and more formal. |
| `speak` | Voice, when that interface exists. |

- **Whose voice.** For now, `text` and `speak` are always in the system's own
  voice. That is a present limit, not a permanent one. `email` may be sent from
  the system's address or from the person's, and the person's address is gated.
- **Choices and mechanics (change 5).** Who, where and what to say are choices:
  `via` is optional, since the tool can use how the person likes to be reached.
  The address and the sending are mechanics.
- **Rephrased by default, exact on request.** Planning gives what to say. By
  default a wording step renders it for the person and the medium: their
  preferences, the system's personality, written or spoken. Planning can instead
  send its words exactly as written, for a quote, a relayed message, an address
  or anything else where the wording matters. Until the wording step is built,
  words pass through unchanged.
- **The result.** Each tool's result returns what was actually delivered, after
  any rewording, where it went, and whether it was sent, delivered, read, failed
  or unknown, with the reason. So planning can check that the wording kept its
  meaning.

So a message can wait for the results it reports. The rule that a message never
claims how its own round's calls went becomes general: a call that needs
another's result, or tells of it, goes in a later round.

Every message brings one more round, which sees how the message went and ends
the work. With caching, that round costs little.

### 5. Planning chooses, tools carry out

This is one rule for every tool.
- **Choices are arguments.** A choice is anything that changes what the action
  means or what it leads to: who, what, where, when, how much. The test is whether
  the person could care which way it went.
  - Planning can name every choice that matters.
  - **Required arguments** are the choices that can't be delegated. The tool's
    schema says which, so whoever builds a tool decides what planning must always
    choose.
  - **An optional argument left out is the tool's to decide,** by a default, by
    the person's known preferences, or by asking a model. How it decides is not
    planning's concern.
- **Mechanics are always the tool's,** never arguments: addresses, APIs,
  protocols, formats, retries.
- **The result says what was used for anything left out,** such as "sent by
  Telegram" or "the terrace table". Planning can then check the outcome against
  the goal, and report it truthfully.
- **Schemas stay simple. A requirement that depends on other arguments is the
  tool's check, not the schema's:**
  - an amount is needed to pay a person, but not to pay a named invoice;
  - a large booking needs a contact number;
  - an email needs an address when none is known.

  The description names the common cases. When planning misses one, the tool
  comes back. That costs one round, not a mistake.
- **Act, or come back with what's needed.** When the tool can carry the call out,
  it acts and reports what it did. When it cannot, it does not act. It returns
  why, and what is needed to call it again: the valid options, or the live facts.
  This covers:
  - an argument that is missing, wrong, or needed by the others (never guessed);
  - values that cannot go together;
  - a choice with no way to decide it;
  - a condition that failed;
  - a call that needs a yes;
  - a person who can't be reached.
- **Planning can state conditions in the call,** such as "only if she's alone".
  Without one, the tool takes the safe default, which for speech means coming back
  when others are present.
- **A tool with effects checks its own record and does not repeat an action**
  already done. It comes back saying so. Each tool's description says whether it
  is safe to repeat.

### 6. Planning's text is its report to the system

In the model's own terms the system is the `user`: every `user` turn is the system
briefing planning or reporting back (change 1), and people appear only as tagged
content inside those turns. So planning's text is its reply to the system, and
that reply is planning's notes:
- its later rounds see the text in the exchange;
- later work sees them all, in the episode's short view, capped for an unusually
  long work, whose full record stays available by episode look-up;
- it is not meant for any person. Those who inspect the system, such as the
  owner in the activation viewer, can still read it.

What people receive comes only from the calls, and the instruction says so
plainly. The tool that carries episode notes goes.

This works with the model's habits, not against them:
- **The model answers in text whoever addresses it,** and here that is the
  system.
- **Text survives from round to round on every provider,** where a model's own
  thinking may not.

**The risk:** a reply meant for a person, written as text, would be kept as a note
and never sent. The framing makes it unlikely, because the model knows who reads
its text. The first suite case for this design still checks it: a plain question
must come back as a message call. If that fails often, the fallback is a notes
tool, with stray text bounced back as news (see the options).

### 7. What an episode shows

Short-term memory and recall show an episode's **short view**. It is a selection
of the episode's own recorded parts, made by code, never a summary:
1. the input, and the meaning understanding recorded;
2. then, in the order they happened:
   - planning's notes;
   - each call with an effect, with its outcome. Messages are calls too, so they
     appear with the text delivered;
   - each offer taken in;
3. how it ended.

Calls from one round sit together. Look-ups are left out, since they changed
nothing. A long work's notes are capped.

Today's view shows no calls and no outcomes. So a later stimulus cannot tell
whether an email was already sent, unless a message happened to say so.

An **episode look-up**, like reading a story, reads one episode's full record by
its E label, wherever planning saw it: in short-term memory, in recall, or in a
matter.
- It holds everything the short view leaves out, such as what a search found,
  what a matter view showed, and each result in full.
- A long record comes in pages.
- Change 11's episode search is how planning finds an episode it was not shown.

**Both views apply the same filters, part by part:**
- **The reader's audience.** A part placed for someone else is left out, silently,
  with no marker, since its existence would leak.
- **Forgetting.** Memories forgotten since the episode are left out.
- **Outside content.** It is never shown raw: a part resting on it appears through
  its digest, or is marked as withheld.

So nothing is visible in the short view and hidden in the full one; the full one
just has more parts to filter.

The one difference is retention. The system can purge an episode's full detail
while its short view remains, and the look-up then says the full record is no
longer kept.

Raw thinking is never shown outside its own work, not even in the look-up.
- It is a stream, not conclusions.
- It is unreliable across models.
- It is large.

ADR-0355's summaries stay in the diagnostic record. Planning's notes are the
thinking it chooses to keep. Thinking summaries in the look-up, clearly marked,
are an option for later, if planning needs its old reasoning.

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
  lets planning choose the medium.
- **Fixed rules for which choices a tool may make.** An earlier version let a
  tool fill a missing choice only from known preferences, and never pick
  otherwise. Change 5 instead lets planning name any choice that matters, and
  leaves an optional one to the tool, however it decides, as long as the result
  says what was used. That is how people delegate, and it lets tools get smarter
  without planning changing.
- **Requirements that depend on other arguments, encoded in the schema**
  (`if`/`then`, `oneOf`). Models fill complex schemas less reliably, and
  providers' strict modes support only part of it. Change 5 keeps schemas simple
  and lets the tool come back.
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
- **A notes tool, with text given no use.** Any text is then a mistake, so it can
  be caught: dropped from the exchange and bounced back as news, with one more
  round so a lost reply gets its chance. That makes a reply written as text
  detectable. But once the system is the briefer, bouncing planning's reply to
  that system is odd, and the mistake is less likely anyway. It is kept as the
  fallback if the suite shows replies written as text.
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
- **How the wording step is built.** Change 4 makes rewording the default, so the
  interface is part of this proposal: planning gives what to say, with an "exactly
  as written" switch, and the result shows what was delivered. The step itself is
  its own design: which model, how preferences and personality reach it, and what
  it may never change, such as times, names and claims.
- **For `speak`: presence, and the question of private content.** Who is around
  belongs in the situation. Whether code should refuse to speak private content
  when others are present is a question for the audience and privacy work.

## How it will be judged

The rewritten instruction is judged on the ADR-0337 suite, with invented data and
repeated samples. These cases come first, because each is a place where the
model's trained habits pull against the design:

1. **A plain question comes back as a message call, not as text.** This is
   change 6's risk.
2. **A clear request is simply done.** "Remind me at 9" is not second-guessed or
   asked about.
3. **A two-part request meets both parts.**
4. **No unprompted extras:** no menus of services, no "anything else?", no
   questions nobody needed.
5. **A plain absence gets a plain answer, with no hedging** about what the system
   might not see.
6. **A message never reports on a call from its own round.**
7. **A stimulus from the system itself,** such as a reminder coming due, is
   handled as what it was set up to do.
8. **Outside content sets no goal by itself.** An invoice email is reported, not
   paid.

## What it leaves open

- **The exact tagged shape of planning's context.** The working doc's raw
  exchange shows one rendering, with invented data. It is settled in the ADR.
- **How "what was done" renders for each tool.**
- **The round limit, and caching details for each provider.**
- **Whose side planning takes in a household,** when one person's stimulus
  affects another. It is deferred while the owner holds full control.
- **How the change splits into ADRs.** A suggestion:
  - one for the exchange: changes 1–7, with ADR-0338's amendment;
  - one for memory: changes 8, 10 and 11;
  - one for the tools: changes 4, 5 and 9.

  The instruction would ship with the first one's implementation, as
  understanding's did with its renderer. The same change aligns two pieces of
  understanding's wording, with an understanding suite run, and changes nothing
  else there:
  - "the system briefs you with", in place of "provides you with";
  - always in mind covers "how they like things done", which is where
    preferences live (ADR-0338's person block). Their default values wait for the
    user model and persistent identity.
