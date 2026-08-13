# 142. Each ingestion source is its own stage, its own operation and its own row

- Status: Proposed
- Date: 2026-08-12

## Context

ADR-0140 adds email as the system's **second** ingestion source. The surface it
would be wired into holds exactly one, and ADR-0140 declined to guess: §14 defers
the question by name to **#1030**, with the firing condition "**Fires with the
implementing lane, before it wires the second stage**". That condition has fired.
This ADR is that decision.

### The state on `main`, read rather than remembered

- `Engine.__init__` takes `ingestion: IngestionStage | None = None` and stores it
  as one attribute; `Engine.ingest` invokes that one stage or raises
  `ConfigurationError` when it is absent. **One stage, structurally.**
- `service/scheduler.py`'s job table carries one ingestion row:

  ```python
  ("calendar_reader", settings.calendar_reader_interval, engine.ingest),
  ```

- `app/composition.py` builds three separate `CalendarReader` instances —
  `facet_reader`, `ingestion_reader`, `upcoming_reader` — from
  `_build_calendar_reader(settings)`, and passes the second into the one
  `IngestionStage`. Its comment already states the rule the rest of this ADR
  generalises: "**Wired on the path, never on the interval.** The path configures
  the source and the interval arms the cadence".
- `Settings` carries `calendar_reader_path`, `calendar_reader_interval`,
  `calendar_upcoming_interval` and `calendar_upcoming_lead` as flat fields. There
  is no source registry, no list-valued source configuration and no mapping from
  a source name to anything.

### The three ways a lane could satisfy ADR-0140 §13 and be wrong

#1030 enumerates them and they are real, because §13's registration item was
written for the single-configured-source case:

1. replace the calendar's stage and row with email's — email ingests, the
   calendar silently stops;
2. retain the calendar's and never schedule email — `email_reader_interval` is
   accepted at load and arms nothing;
3. grow `Engine` a second ingestion operation, or parameterise the existing one,
   and add a second scheduler row.

All three pass every test ADR-0140 §13 requires. That is ADR-0103 §9's test
failing: two lanes make incompatible choices and both claim compliance.

### What already binds, and is not relitigated here

- **ADR-0083 §7** — one loop, a table of named jobs, per-job intervals, **serial**
  execution, fixed delay after completion, "disabled" spelled `None` and never
  `0`, and a failing job never taking the process down.
- **ADR-0083 §8** — "Every scheduler job is a public `Engine` call", the scheduler
  is a peer above the composition root holding an `Engine` and nothing else, and
  the `Engine` "grows a maintenance surface" that is concrete `orchestration`
  surface rather than `core` contract surface. `Job.run` is typed `JobBody`, whose
  own docstring reads "One scheduled unit of work: a **no-argument** call on the
  engine façade."
- **ADR-0093 §3** — a source's two consumers "read at their own cadence" and
  "Neither may derive its answer from the other's reading".
- **ADR-0093 §6** — the job's body "is a public `Engine` call and holds no store,
  no sensor and no subsystem import"; ingestion is never wired into a turn.
- **ADR-0093 §7** — flat `Settings` fields, no registry, disabled by default
  because "nothing may read a user's personal files because a default said so",
  and at most one outstanding worker per reader instance.
- **ADR-0093 §11** — the source registry, "and with it a **configurable display
  label** … and an instance-distinguishing `reported_by`", fires **at the third
  source**. Email is the second (ADR-0140 §9), so it does not fire here.
- **ADR-0096 §5** — each consumer of a source holds its **own** reader instance.
- **ADR-0097 §5**, **ADR-0133 §2** — the read is gated on a live grant for that
  source's declared identity, scoped by use, and the three uses are independent.
- **ADR-0132 §3, §4** — the shape of an independence clause, stated for the
  second consumer of one source: "Neither field is `calendar_reader_interval`,
  and neither is derived from it. That field arms the ingestion job and nothing
  else; arming or retuning one of these two changes ingestion's cadence in no
  way, and arming ingestion arms no producer."
- **ADR-0140 §12** — the seven email `Settings` fields, `email_source_path` and
  `email_reader_interval` among them, both defaulting to `None`, with a
  configuration setting the interval and not the path refused at load.
- **ADR-0140 §13** — the wiring deliverable, whose precondition is this decision.

### This is the mirror of ADR-0132, and that is the cheapest way to read it

ADR-0132 answered *one source, two consumers*: the upcoming-event producer got
its own reader instance, its own grant scope, its own `Settings` interval, its
own no-argument `Engine` operation (`notice_upcoming_events`) and its own
scheduler row (`calendar_upcoming`) — beside ingestion's, deriving nothing from
it. This ADR answers *one consumer, two sources*, and the constraint set is the
same one. What is new is only that the multiplied thing is the source rather than
the use.

### An honest statement of what this ADR is not allowed to settle

- **It is not a contract change.** `ingest` is not a member of the
  `AssistantEngine` Protocol in `core/protocols.py`: no ingestion operation
  appears among that Protocol's members, and none of its members delegates to an
  ingestion stage. It is concrete surface on `orchestration`'s `Engine`, which is
  where ADR-0083 §8 puts a maintenance surface — "not `core` contract surface".
  Golden rule 5 is therefore not engaged, no `core` file is touched by anything
  this ADR rules, and ADR-0140 §13's "adds this surface to `core` and no other"
  stands unaffected either way, which §14 says in as many words.
- **It is not ADR-0093 §11's source registry**, and §8 below refuses to become
  one early.
- **It does not rule a second instance of one source type.** ADR-0140 §14 defers
  a second mail account to §11's instance-distinguishing identity, and nothing
  here reaches it.
- **It does not re-open cadence figures.** ADR-0140 §12 fixed
  `email_reader_interval`'s default and range in a marked clause; this ADR rules
  what having it *means*, not what it holds.
- **It does not decide the reader, the facet or the fetcher.** Those are
  ADR-0140's, ratified.

## Decision

### 1. Cadence independence is ruled, not implied — the clause ADR-0140 §14 left owed

ADR-0140 §14 is explicit that this is missing: "**The independence is deferred
rather than assumed:** nothing in this ADR rules in a marked clause that email
ingestion is armed independently of the calendar's — it follows only by inference
from the two interval fields being separate, which in this document's regime
obligates nobody … **The decision #1030 tracks owns that clause.**" It is ruled
here, in ADR-0132 §4's shape.

> **Normative.** Each configured ingestion source is armed on its own interval,
> independently of every other. A deployment may run any subset of the configured
> sources' ingestion jobs, including none and including all.

> **Normative.** No ingestion source's arming field is derived from, defaulted
> from, or conditioned on another source's. Arming or retuning one source's
> ingestion changes no other source's cadence, and arming one arms no other.

**These are two clauses because they fail separately.** The first is about what a
deployment may express; the second is about what an implementation may do with
what was expressed. A lane can honour the first — both jobs exist — while
breaching the second by defaulting `email_reader_interval` to
`calendar_reader_interval` when the former is unset, which would silently arm a
read of the user's mail because they had armed a read of their calendar. That is
the consent failure ADR-0093 §7 exists to prevent, arriving through a default
rather than through a flag.

**Independence in *both* directions is the point, and the corpus has said so
before.** ADR-0132 §4's clause is bidirectional for the same reason, and
`Engine.notice_upcoming_events` restates it: "arming or retuning it changes
ingestion's cadence in no way and arming ingestion arms no producer. A deployment
may run either, both or neither."

### 2. Wiring is keyed on the source's path; arming is keyed on its interval — per source

> **Normative.** A source's ingestion stage is constructed by the composition
> root when **that source's** path field is configured, and its scheduler row is
> armed when **that source's** interval field is set. Neither decision reads any
> other source's fields.

This is the calendar's existing shape stated so that it generalises rather than
being re-derived. `app/composition.py` already says it — "**Wired on the path,
never on the interval.** The path configures the source and the interval arms the
cadence, so ADR-0093 §7a's facet-only state is one where the stage exists and no
job is armed" — and `_build_calendar_reader` already returns `None` on an unset
path and consults no interval.

> **Normative.** A source whose path is configured and whose interval is unset is
> a legal, meaningful state per source: its ingestion stage exists and its
> ingestion operation reaches that source's grant gate when called rather than
> refusing as unwired, and no scheduler row is armed for it.

**"Reaches its grant gate" rather than "succeeds", and the distinction is
load-bearing.** An unarmed source's operation is a *wired* operation with no
caller, so what it must not do is raise §6's `ConfigurationError` — the refusal
that means "no source is configured". What it does after that is §7's and is
unchanged: with no live `INGEST` grant it raises `SourceNotGrantedError`, which
is the ordinary state of a source the user has not granted, and nothing in this
clause lets an unarmed source be read without one. The two refusals are different
facts, which `Engine.ingest` already says in its own words — "that one is a
deployment that cannot ask, this one is a user who has not said yes".

**That state is what makes the facet independent of ingestion**, which is
ADR-0093 §3's rule and ADR-0140 §13's per-consumer instance requirement working
together: a deployment may contribute the email facet to a turn while never
ingesting email on a timer. It is also what keeps the arming decision one field
wide — the operator arms a source by setting one interval, and unsets it by
clearing that one interval, with no second field to remember.

**The incoherent fourth state is already refused at load and is not this ADR's to
add.** ADR-0093 §7a refuses `calendar_reader_interval` set with
`calendar_reader_path` unset, and ADR-0140 §12 rules the identical refusal for
email in a marked clause. So "the interval arms nothing" — #1030's failure mode 2
— cannot be reached by configuration; it can only be reached by a lane that
accepts the field and wires no row, which is what §4 and §9 below close.

### 3. One stage per source, held as its own collaborator — never a multiplexing stage

> **Normative.** The engine holds one `IngestionStage` per configured ingestion
> source, each over its own `Reader` instance. No ingestion stage holds more than
> one reader, and no ingestion stage dispatches over a collection of readers.

**The stage is already the right object and needs no change.**
`orchestration/ingestion.py`'s `IngestionStage` takes one `reader`, one `writes`
and one `grants`, reads the reader once, and puts each proposal through the write
stage. A second source is a second construction of that class, with zero new
machinery — which is the strongest available evidence that the seam was cut in
the right place at leg 6.

**Its own reader instance is ADR-0096 §5's rule, and ADR-0140 §13 already carries
it into this lane's deliverable**: "both consumers above are wired into the engine
on **separate** `EmailReader` instances, neither sharing the other's". Composition
already does this three ways for the calendar (`facet_reader`,
`ingestion_reader`, `upcoming_reader`), so email's ingestion reader is a fourth
instance and the calendar's are untouched.

**A multiplexing stage — one stage holding many readers, read in a loop — is
refused, and the reason is cadence rather than taste.** One stage behind one
operation is one scheduler row, and one row has one interval. To give the
multiplexer two cadences you must give it a schedule of its own, which is
ADR-0093 §11's registry with a timer in it, arriving at the second source instead
of the third. It also fuses the failure modes: a `ReaderError` from one source
aborts the loop, and the sibling source is not read at all that tick — a coupling
§7 refuses and which the serial-loop design already avoids for free by giving
each source its own job.

**The single-outstanding-worker reservation is untouched.** ADR-0093 §7 keys it
to a reader instance, and each source's ingestion holds its own instance, so two
sources' ingestion can never contend for one reservation. ADR-0083 §7's serial
loop makes the stronger statement anyway: the two jobs never run concurrently at
all, which is exactly ADR-0132 §3's "its read never runs concurrently with the
ingestion job's. Its cost is duty cycle, not contention."

### 4. One no-argument `Engine` operation per source, and no ingestion operation takes a source

> **Normative.** Each configured ingestion source is driven by its **own** public
> operation on the concrete `orchestration` engine, returning that source's
> `IngestionReport`. No ingestion operation takes a source argument, a source
> name, or any argument at all.

> **Normative.** An ingestion source's scheduler row holds that operation as a
> **bound method of the engine** — not a wrapper, a closure, a `functools.partial`
> or any other object standing in for it.

**The discriminator is the option that has to be argued down, because nothing in
the corpus literally forbids it.** ADR-0083 §8 says "Every scheduler job is a
public `Engine` call", and `functools.partial(engine.ingest, "email")` satisfies
`JobBody` structurally and is, in a sense, a public `Engine` call. Four things
decide against it, and the fourth is the one a lane would not find:

- **It defeats the reason the operation takes no argument today.**
  `Engine.ingest` states it: "**Takes no argument, deliberately.** The reader is
  given its own source and its own bound (§1, §5), so `read()` takes none either:
  a caller able to widen the read is a caller able to defeat the bound." A source
  selector is a narrower version of the same caller — it cannot widen a bound, but
  it does move the choice of *what is read* from the wiring to the call site.
- **It moves a wiring fault from type-check time to run time.** With two named
  operations, a scheduler row naming the wrong one does not compile under `mypy`
  strict. With a selector, `engine.ingest("emial")` is well-typed and fails at the
  first tick, in a job whose failure is logged and retried forever — ADR-0022
  §4a's "reports health while doing nothing", reached by a typo.
- **It requires the engine to hold a mapping from a source name to a stage**, and
  that mapping is ADR-0093 §11's registry in miniature, arriving at the second
  source. §8 below refuses that trade on its own terms.
- **It collapses the operation trace, and the report cannot rescue it.**
  `Engine._tracked` takes a `seam` string that is, at every one of its call sites
  on `main`, the public method's own name — `"ingest"`, `"purge_expired"`,
  `"notice_upcoming_events"`, `"consolidate"` — and ADR-0119 §8 makes that the one
  wiring point for the `OPERATION` trace. A single parameterised operation emits
  one seam for every source. The obvious repair — put the source in the trace —
  is already refused: `_ingested`'s docstring records that
  `IngestionReport.source` "is deliberately left off" because ADR-0119 §2 "admits
  no string into a trace that is not an identifier, an enum member, a literal
  written here or an exception's class name", and a reader's declared identity is
  read at runtime. So under a discriminator, no `OPERATION` trace can say which
  source ran or which one is failing, and no smaller fix restores it. Distinct
  operations make distinct literal seams *available* — §9's test 10 is what makes
  them owed, because an implementation can add the operation and still route it
  through the existing seam string, throwing away the one property this bullet
  chose the shape for.

**The bound-method clause is an addition, and it is scoped to these rows.**
ADR-0083 §8's sentence does not say "bound"; the scheduler's own `jobs_for`
docstring does — "Each job holds a **bound method** of this object and nothing
else" — and every row on `main` satisfies it. This ADR makes it binding for the
ingestion rows it rules and claims nothing about the other four; generalising it
to every job is a scheduler decision and is not this one's to take.

### 5. The reader's declared identity is the stem, and the existing operation is renamed

> **Normative.** For each ingestion source, one **stem** names all three of its
> artefacts: the engine operation is `ingest_<stem>`, the scheduler row's name is
> `<stem>_reader`, and the arming `Settings` field is `<stem>_reader_interval`. A
> stem matches `[a-z][a-z0-9_]{0,56}`. It is the source's declared `Reader.name`
> where that matches; where it does not, the decision adding that source names a
> matching stem explicitly, and no stem is ever derived silently.

> **Normative.** `Engine.ingest` is renamed `Engine.ingest_calendar` and its
> constructor parameter and attribute are renamed from `ingestion` to
> `calendar_ingestion`, in the same change that adds the second source. Behaviour,
> return type, refusal conditions and the scheduler row's **name** are unchanged
> by the rename.

**The rule is satisfied by everything already on `main`, which is the point of
stating it.** The calendar reader declares `"calendar"`; its row is
`calendar_reader`; its arming field is `calendar_reader_interval`. ADR-0140 §12
ratified `email_reader_interval` and fixes the email reader's identity as
`"email"`, so `email_reader` and `ingest_email` are determined rather than
chosen. Three artefacts named by one stem are three artefacts a registry can
later enumerate mechanically (§8), which is worth more than the saved keystrokes.

**The grammar is the intersection of the three domains a stem has to be legal
in, stated once rather than left to be discovered.** `ingest_<stem>` is a Python
method name; `<stem>_reader_interval` is a `Settings` field name; and
`ingest_<stem>` is also the `seam` string `Engine._tracked` passes into the
`OPERATION` trace, which `core/types.py` types as `TraceLabel` and validates
against `[a-z][a-z0-9_]{0,63}` — lowercase ASCII, leading letter, sixty-four
characters. `ingest_` spends seven of those, which is where the fifty-seven comes
from. `[a-z][a-z0-9_]{0,56}` satisfies all three at once, and both stems this ADR
governs — `calendar` and `email` — match it.

**A declared identity satisfies none of that, and the corpus is explicit that it
need not.** `Reader.name` returns `str`, and the identity that lands on a reading
is `Identifier` in `core/types.py` — "A non-blank, stripped identifier that has a
UTF-8 encoding", and nothing more; `VisibleIdentifier` is a separate type and #62
still holds the canonical-syntax question. So `"rss-feed"` (no legal method name),
`"RSS"` (a legal method name and an illegal trace label) and a fifty-eight
character lower-case identity (legal everywhere except the seam, by one character)
are all identities a future reader may declare in good standing. A reader's
identity is ADR-0093 §7's, decided for the reader's own reasons, and a naming rule
of the engine's does not get to reach back and constrain it — so the derivation
yields where it must, and the source's own decision names the stem instead.

**The failure this forecloses is silent, which is why the grammar is on the stem
rather than on a reviewer's eye.** ADR-0119 §5 makes the emitter subordinate to
the work — `Engine._tracked` states it as "no trace failure reaches `coro`'s
caller" — so an over-long or upper-case seam does not fail the operation. It
raises inside the emitter, is swallowed, and that source's ingestion simply emits
no `OPERATION` record at all: the operation succeeds forever while the
observability §4 chose this whole shape to buy is gone, with nothing anywhere
saying so.

**One stem across all three artefacts, rather than a per-artefact allowance.** A
row name and a `Settings` field could each carry a hyphen where a method cannot,
so a looser rule would let one source's three artefacts disagree — which is the
enumeration §8 relies on becoming three lists instead of one.

**The scope of the rule is the three artefacts this decision creates, and the
path field is deliberately outside it.** `calendar_reader_path` and
`email_source_path` do not share a stem, and that asymmetry is ratified —
ADR-0140 §12's table is a marked clause. Stretching this rule over the path field
would amend a ratified figure to buy symmetry nobody reads, so it does not reach
there, and the disagreement is recorded rather than smoothed over.

**The rename is the whole reason this ADR bothers with names at all.** #1030's
defect is that a single unnamed ingestion surface silently means "the calendar".
Leaving `Engine.ingest` in place while adding `Engine.ingest_email` re-creates
that defect one level down: the calendar becomes the unnamed default, the third
source arrives beside `ingest`, `ingest_email` and `ingest_rss`, and the next
lane reads `ingest` as "ingestion" rather than as "the calendar's ingestion" — the
exact misreading this document exists to close. The asymmetry is also what makes
the registry migration harder to see when §8's condition fires.

**Its cost was measured rather than guessed, and it is small.** `Engine.ingest`
has exactly one production call site — the scheduler's row in `jobs_for` — and so
does the constructor keyword `ingestion=`, in `app/composition.py`. Everything
else is docstring cross-references within `orchestration/` and test references
under `tests/app/test_composition.py` and `tests/service/test_scheduler.py`.
Every one of those files is already opened by §9's deliverables, so the rename
adds no file to the lane's diff.

**The row name is not renamed, and that is a separate fact.** `Job.name` is
"Stable identifier for the log and for `hub_ready`'s job list", so it crosses the
wire to a client. It is already `calendar_reader` and already satisfies the rule
above, so nothing is owed; a lane that "tidied" it to match the method name would
be making a wire-visible change for no reason.

### 6. Refusal is per source, and each refusal names its own source

> **Normative.** Each ingestion operation refuses with `ConfigurationError` when
> **its own** stage is absent, and its message names that source's own
> configuration. No ingestion operation reports another source's state, stands in
> for another source's operation, or succeeds vacuously because another source is
> configured.

**This is `Engine.ingest`'s existing posture, per source rather than global.**
Today the message names `ASSISTANT_CALENDAR_READER_PATH` and explains that
"Configuration says where a source is; a grant says whether it may be read, and
neither stands in for the other". Email's refusal names its own path variable, on
ADR-0140 §12's field. The reason is unchanged and is ADR-0022 §4a's: "an empty
report would be indistinguishable from a source that had nothing to say, so a
deployment whose stage failed to wire would look healthy forever while ingesting
nothing."

**One shared message is the trap here.** An operator told "no ingestion stage is
wired" by an engine that ingests the calendar every hour looks in the wrong place,
which is the failure `Engine.ingest`'s own docstring already names about a
different pair of conditions — "they are different facts and an operator told the
wrong one looks in the wrong place."

### 7. Grants, failure and serialisation are per source, and unchanged in kind

> **Normative.** Each source's ingestion read is gated on a live `INGEST` grant
> for **that source's** declared identity. No grant on one source authorises a
> read of another, whatever its scope.

ADR-0097 §5 and ADR-0133 §2 already rule this; it is restated because a shared
stage or a shared operation is exactly how it would be breached by accident, and
because ADR-0132 §2 found the equivalent restatement worth making across *uses*
of one source ("a live `INGEST` grant on this calendar authorises this read no
more than a `FACET` one does"). The check stays where ADR-0093 §1 and ADR-0097 §5
put it — inside the stage, not the reader — so each source's stage carries its own.

> **Normative.** One source's ingestion job failing, refusing for want of a grant,
> or being unarmed neither disarms, delays beyond ADR-0083 §7's serial duty cycle,
> nor alters the outcome of any other source's ingestion job.

ADR-0083 §7's "A failing job never takes the process down" and ADR-0093 §6's "A
failing sensor job never takes the process down. It is logged with its class and
retried at its next due instant" are unchanged and now have a sibling to be
independent *of*. The clause is worth marking because the multiplexing alternative
§3 refuses is precisely the design in which it becomes false.

**Serialisation is ADR-0083 §7's and is not relaxed.** The two ingestion jobs run
on one loop, one at a time, each re-armed from its own completion, so the honest
statement of the cost is duty cycle: a long calendar read delays a due email read
by its own duration. ADR-0083 §7 accepts that explicitly — "A long job delays its
siblings … a missed or late tick is never a correctness bug" — and §5 of ADR-0093
is why it stays true for readers specifically: a reader's bound moves with the
clock, so every run recomputes its window and nothing accumulates behind a cursor
that does not exist.

### 8. No registry, and an honest account of what the third source pays

> **Normative.** This decision adds no source registry, no list-valued or
> mapping-valued source configuration, and no runtime mapping from a source name
> to a stage or to an operation. Each source's stage, operation, row and fields
> are enumerated statically.

**ADR-0093 §7's precedent is the whole argument and it is quoted rather than
paraphrased**: "The precedent is ADR-0083 §7's own: `retention_purge_interval`,
`conversation_sweep_interval` and `observation_interval` are three flat fields,
not a table. A registry is a schema decision with a validation story, and one
source does not buy it. Revisit at the third source". Two sources do not buy it
either — the increment from one to two is one field pair, one stage, one method
and one row — and ADR-0093 §11 names the third source as the trigger, which
ADR-0140 §9 confirms email does not reach.

**What three sources cost under this shape, counted rather than waved at:** each
source carries **five** enumerated artefacts — a `Settings` field pair, a stage
construction in `app/`, an engine attribute, an engine operation and a scheduler
row — so three sources carry fifteen. And at the third, ADR-0093 §11's registry
*and* its configurable display label *and* its instance-distinguishing
`reported_by` all fire together, because §11 defers them as one entry. So the
third source's lane pays a schema decision it was always going to pay, plus the
mechanical collapse of those five per-source artefacts into one registered entry.

**Nothing here forecloses that, and §5 is why.** The registry replaces an
enumeration, not a mechanism: all five of a source's artefacts are named from one
stem by one rule (§5), so the migration is a fold over a list of stems rather
than a redesign. A discriminator-carrying `ingest(source)`
would not have been closer to the registry — it would have been the registry's
dispatch half without its schema half, validation story or display label, which
is the worst of the two shapes and the one §4 refuses.

### 9. The work order: what the implementing lane owes

> **Normative.** The lane implementing ADR-0140 §13's ingestion-wiring
> deliverable owes each of the following four items, and the test list below is
> part of the obligation rather than advice about it.
>
> 1. **The rename** (§5): `Engine.ingest` → `Engine.ingest_calendar`, its
>    constructor keyword and attribute `ingestion` → `calendar_ingestion`, and
>    every reference in `src/` and `tests/` updated. No behaviour change, and the
>    `calendar_reader` row name untouched.
> 2. **The second operation and its stage** (§3, §4, §6): `email_ingestion:
>    IngestionStage | None = None` on `Engine.__init__`, and a public
>    no-argument `Engine.ingest_email` returning `IngestionReport`, tracked
>    through `_tracked` under its own seam, refusing with a `ConfigurationError`
>    that names `ASSISTANT_EMAIL_SOURCE_PATH`.
> 3. **The composition-root wiring** (§2, §3): an `IngestionStage` over its own
>    `EmailReader` instance — never the one the `context/` adapter holds —
>    constructed when `email_source_path` is set and passed as
>    `email_ingestion`, and `None` otherwise.
> 4. **The scheduler row** (§1, §2, §5): `("email_reader",
>    settings.email_reader_interval, engine.ingest_email)` on `jobs_for`'s table,
>    armed only when that interval is set.

> **Normative.** The lane owes each of the following ten tests, each named by the
> breach it catches. A test item omitted is a defect rather than a scoping choice.
>
> 1. **Both sources, differing intervals, both retained (§1, items 1–4).** With
>    both paths and both intervals configured at *different* values, both stages
>    are held, both rows are armed under distinct names, and each row's interval
>    is its own source's. Catches #1030's option 1 — email's wiring replacing the
>    calendar's — which every single-source test passes.
> 2. **Path without interval arms nothing and disables nothing (§2, items 2–4).**
>    With the email path set, `email_reader_interval` unset and a live `INGEST`
>    grant on `"email"`, no `email_reader` row is armed and `Engine.ingest_email`
>    **still succeeds when called directly**. Both halves are asserted: a lane
>    that keys the stage off the interval passes the first half and fails the
>    second. The grant is part of the arrangement rather than incidental to it —
>    without one the operation raises `SourceNotGrantedError` (§7) and the test
>    would assert the wrong refusal.
> 3. **Either source alone (§1, §2, items 2–4).** With only the email source
>    configured, `email_reader` is armed and `Engine.ingest_calendar` refuses;
>    with only the calendar's, the mirror. Catches an implementation in which
>    email ingestion requires a configured calendar, or the reverse.
> 4. **Every consumer on its own reader instance (§3, item 3).** The email
>    ingestion stage's reader is not the instance the email `context/` adapter
>    holds, and is no calendar reader either. Catches ADR-0096 §5 breached by a
>    lane reusing one construction, which no behavioural test in this list would
>    notice.
> 5. **No argument, and the row holds the bound method itself (§4, items 1, 2,
>    4).** Each ingestion operation's signature admits nothing but `self`, and
>    each ingestion row's `run` is the engine's own bound method — its
>    `__func__`/`__self__` identifying the operation and the engine — rather than
>    a wrapper. Catches the `functools.partial` shape, which satisfies `JobBody`
>    and passes every behavioural test in this list.
> 6. **Each refusal names its own source (§6, items 2, 3).** With only email
>    configured, `Engine.ingest_calendar` raises `ConfigurationError` whose message
>    names the calendar's path variable and not email's; with only the calendar
>    configured, the mirror for `Engine.ingest_email`. Catches one shared message,
>    which passes any test asserting only the exception type.
> 7. **No grant substitutes for another source's (§7, items 2, 3).** With a live
>    `INGEST` grant on `"calendar"` and none on `"email"`, `Engine.ingest_email`
>    raises `SourceNotGrantedError` while `Engine.ingest_calendar` succeeds, and
>    the mirror. Catches a stage constructed over the wrong source's grant lookup.
> 8. **One source's failure leaves the other's job running (§7, items 2, 4).**
>    With both rows armed and the email ingestion raising `ReaderError` every
>    tick, the calendar row continues to run at its own interval and the scheduler
>    stays up. Catches the coupling a multiplexing stage would introduce.
> 9. **The armed set and its names (§5, items 1, 4).** `Scheduler.job_names`
>    reports `email_reader` beside `calendar_reader` when both are armed, and the
>    calendar row's name is unchanged by the rename in item 1. Catches a
>    wire-visible rename of a stable identifier.
> 10. **Each source's operation emits its own trace seam (§4, §5, items 1, 2).**
>    A calendar ingestion and an email ingestion each emit their `OPERATION` trace
>    under their own stem's seam — `ingest_calendar` and `ingest_email` — and
>    neither emits under the other's. Catches an implementation that adds the
>    second operation and routes it through the first's seam string: it passes
>    every other test in this list while leaving no `OPERATION` record able to say
>    which source ran or which one is failing, which is the property §4 chose this
>    shape for and which ADR-0119 §2 forecloses repairing from the report.

**The lists were audited against each other rather than grown, and the counts are
counted rather than incremented.** This ADR carries **fifteen** marked clauses:
twelve in §§1–7, one in §8, and the two work orders in this section. Each of the
twelve has at least one deliverable item and at least one test item —
§1 → items 1–4, tests 1 and 3; §2 → items 2–4, tests 2 and 3; §3 → item 3, tests
4 and 8; §4 → items 1, 2 and 4, tests 5 and 10; §5 → items 1 and 4, tests 5, 9
and 10; §6 → items 2 and 3, test 6; §7 → items 2–4, tests 7 and 8. In the other
direction, every deliverable item is exercised: item 1 by tests 1, 5, 9 and 10;
item 2 by tests 1, 2, 3, 5, 6, 7, 8 and 10; item 3 by tests 1, 2, 3, 4, 6 and 7;
item 4 by tests 1, 2, 3, 5, 8 and 9. **Four** deliverable items, **ten** tests,
and no clause left without either.

**§8's clause is the one that is review-enforced rather than test-enforced, and
saying so is better than inventing a test for it.** It is a refusal binding a
later lane and a later ADR — no registry, no list-valued configuration, no
name-to-stage mapping — and the only honest test of an absence at this scope
would assert over module internals, which is the kind of check `CONTRIBUTING.md`
keeps out of a test suite. A reviewer reads the diff for it.

**This section does not widen ADR-0140 §13's fifteen-item test list**; it adds
its own, against its own clauses. §13's list is scoped to §13's deliverables and
stays exactly as ratified.

### 10. Deferred, by name, each with the condition that fires it

- **The source registry, its configurable display label, and an
  instance-distinguishing `reported_by`.** ADR-0093 §11's entry, unchanged. Fires
  at the third source; §8 records what it will cost and why this shape does not
  make it harder.
- **A second instance of one source type** — a second mail account, a second
  calendar. ADR-0140 §14's deferral, unchanged: it fires with §11's
  instance-distinguishing identity, and nothing here reaches it. Two *instances*
  are not two sources under §5's naming rule, because they would share a declared
  identity.
- **Concurrency between ingestion jobs.** ADR-0083 §7's serial loop governs and
  its own revisit condition — "when a job's typical runtime approaches its
  interval" — is the trigger. §7 above states the duty-cycle cost honestly rather
  than pre-empting that revisit.
- **Event-driven reading, for any source.** ADR-0140 §14's deferral, unchanged:
  it "fires with a decision about read cadence … and would reach every reader".
  This ADR rules how *scheduled* cadences coexist and takes no position on
  whether a source should be scheduled at all.
- **A shared `OPERATION` trace dimension for the source.** §4 records that
  ADR-0119 §2 excludes a runtime-read identity from a trace, and this ADR
  routes around it by giving each source its own literal seam. Fires if a
  consumer ever needs the sources compared within one seam, and it is ADR-0119's
  decision rather than this one's.
- **Whether the other four scheduler rows must hold bound methods.** §4's second
  clause binds the ingestion rows only. Fires with a scheduler decision that has
  a reason to generalise it; every row on `main` already satisfies it.

### 11. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 puts the judgement in the later ADR's text and fixes the test: *would
a reader holding only the earlier ADR now act differently, or read one of its
clauses more widely than it now holds?* Applied clause by clause, **the answer is
that no earlier ADR's `Status` line is edited and no dated note is owed on any of
them.** This branch touches one file.

- **ADR-0140 §14's ingestion-cadence entry.** This ADR **discharges** it, at the
  condition §14 itself states ("Fires with the implementing lane, before it wires
  the second stage"), and supplies the clause §14 says the decision "owns". A
  discharge is not a supersession, and ADR-0140 §15 is the precedent in its own
  words, about ADR-0093 §11's fifth deferral: "a discharge is not a supersession:
  §11 defers work and qualifies no rule, and its own entry says such a source
  'owes its own decision'." §14's entry likewise qualifies no rule — it defers
  work and names its owner. A reader holding only ADR-0140 reaches §14, finds the
  deferral, follows it to #1030 and arrives here. **Addition.**
- **ADR-0140 §12's `email_reader_interval` row.** §1 above rules that the field
  arms email's ingestion independently, which is the reading §12's table already
  invites ("the cadence; `None` is disabled"). Had this ADR ruled the *opposite* —
  one cadence for both sources — that row would have become false and a partial
  supersession would have been owed. It rules with it. **Addition.**
- **ADR-0140 §13's ingestion-wiring deliverable.** §9 above supplies the
  precondition §13 names and adds items and tests of its own. §13's own list is
  neither widened nor narrowed, and every sentence of it stays true. **Addition.**
- **ADR-0093 §7's one-source clause** — "Leg 6 configures exactly one source, by
  explicit `Settings` fields. There is no source registry and no list-valued
  source configuration." Both halves survive. The first is scoped to leg 6 by its
  own words and says nothing about leg 11; the second is restated and bound by §8
  above rather than relaxed. Its "Revisit at the third source" is honoured, not
  moved. **Addition, and the narrowest possible use of a clause whose revisit
  condition was available to be stretched.**
- **ADR-0093 §6's ingestion-job clause.** §6 rules that a sensor is driven by a
  job whose body is a public `Engine` call holding no store, no sensor and no
  subsystem import, and that `Engine` "grows an ingestion operation for the job to
  call". §4 above adds a second such operation and a second such job, each
  satisfying every condition §6 states. §6 names no method, so the rename in §5
  makes no sentence of it false. **Addition.**
- **ADR-0083 §7 and §8.** A new row on the job table is an addition of the kind
  ADR-0093 §6, ADR-0130 §5 and ADR-0132 §4 each already made. ADR-0130 §12 made
  exactly this classification for its own row — "a **new row on ADR-0083 §7's
  table**, which is an addition of the kind ADR-0093 §6 already made when it
  added the calendar reader … so growing the table is not one" — and §8's
  maintenance-surface sentence is used as written. §4's bound-method
  clause adds an obligation §8 did not state, scoped to this ADR's own rows, and
  contradicts no sentence of §8: "a public `Engine` call" stays true of a bound
  method. **Addition.**
- **ADR-0093 §11's registry entry.** §8 above declines to fire it early and
  restates its third-source condition. Nothing is discharged and nothing is
  narrowed. **No record owed, and none available.**
- **ADR-0096 §5.** §3 applies the per-consumer reader-instance rule to a second
  source. §5's sentences are about a source's consumers and stay true of each
  source separately. **Addition.**
- **ADR-0132 §3 and §4.** §1 above copies §4's shape for a different
  multiplication — sources rather than uses. ADR-0132's clauses are about the
  upcoming-event producer and the calendar's ingestion, and no sentence of either
  becomes false or wider. **Addition, and a form reused rather than a rule
  reached into.**
- **ADR-0119 §2 and §8.** §4 above *relies* on §2's exclusion of a
  runtime-read string and on §8's one wiring point, and asks nothing of either.
  The trace seam stays a literal written at the call site. **No record owed.**
- **ADR-0089 §3 — applied to this ADR's own marks, reaching no other ADR.** Every
  obligation this document imposes sits inside a mark, including §9's two work
  orders, on ADR-0140 §13's finding that "A work order is the obligation rather
  than the argument for one, so it goes inside the mark". The prose around them
  says what the clauses mean and binds nobody.

**This ADR is marked under ADR-0089** and is in the marked regime: its unmarked
prose supplies no obligation and exists to determine what the marked clauses
mean (ADR-0089 §3). It follows ADR-0098 §11's and ADR-0140 §15's practice — marks
stated while #622's question about ADR-0089's own status is open — and resolves
nothing there.

## Consequences

- **ADR-0140 §13's ingestion deliverable becomes implementable.** Its named
  precondition is discharged, and the lane taking it has four deliverables and
  ten tests rather than three incompatible readings.
- **Cadence independence is a clause rather than an inference.** A lane that
  defaults one source's interval from another's now breaches a marked ruling, and
  a reviewer has a sentence to quote.
- **The engine's maintenance surface grows one method per ingestion source**, and
  that is the cost this shape accepts in exchange for static wiring, distinct
  operation traces and a type error where a selector would have given a runtime
  fault. At three sources ADR-0093 §11's registry fires and collapses it.
- **One rename lands in the email lane's diff.** `Engine.ingest` becomes
  `Engine.ingest_calendar`, touching only files that lane already opens. Nothing
  outside `orchestration`, `service`, `app` and their tests refers to it, and no
  wire-visible name changes.
- **The `calendar_upcoming` row now has a sibling pattern to be read against.**
  Three of the seven scheduler rows are then per-source-per-use — `calendar_reader`,
  `calendar_upcoming` and `email_reader` — named by one rule, which makes the
  table's growth legible where it was previously row by row.
- **Revisit at the third source**, which is ADR-0093 §11's own trigger and not a
  new one. That lane inherits §5's naming rule as the enumeration to fold.

## Alternatives considered

- **A multiplexing `IngestionStage` holding every configured reader, behind the
  existing `Engine.ingest` and the existing row.** The smallest diff, and it fails
  the question: one row is one interval, so `email_reader_interval` would arm
  nothing — #1030's failure mode 2 — unless the multiplexer grew a schedule of its
  own, which is ADR-0093 §11's registry two sources early. It also fuses the
  failure modes (§3) and collapses the operation trace (§4).
- **`Engine.ingest(source: str)` with `functools.partial` in the scheduler
  table.** Rejected in §4 on four grounds, of which the trace argument is the one
  that cannot be repaired by care: ADR-0119 §2 will not admit a runtime-read
  identity into the trace, so no `OPERATION` record could say which source ran.
- **`Engine.ingest()` retained for the calendar, `Engine.ingest_email()` added.**
  The zero-rename option. Rejected in §5: it makes the calendar the unnamed
  default, which is the defect #1030 records reproduced one level down, and the
  rename it avoids costs no additional file in the lane's diff.
- **Firing ADR-0093 §11's source registry now, at the second source.** Tempting
  because it answers this question and the third source's at once. Rejected
  because §11 names the third source as the trigger and because a registry is "a
  schema decision with a validation story" (ADR-0093 §7) whose display-label and
  `reported_by` halves have no subject yet — ADR-0140 §14 records that the label
  "acquires a subject at the second instance of one source type", which has not
  arrived. Deciding it now would mean guessing at requirements the corpus has
  explicitly said it cannot yet see.
- **A shared `ingestion_interval` arming every configured source at one cadence.**
  Rejected: it contradicts ADR-0140 §12's ratified `email_reader_interval` in a
  marked clause, and it is the shape ADR-0132 §4 already refused for the
  equivalent case — "an operator who could not set one without setting the other
  would have one cadence chosen for two jobs with different needs".
- **Deferring the rename to the third source's lane.** Rejected as the more
  expensive ordering: it leaves the ambiguous name in place across the whole of
  leg 11, and the third source's lane is the one already carrying a registry
  migration.
