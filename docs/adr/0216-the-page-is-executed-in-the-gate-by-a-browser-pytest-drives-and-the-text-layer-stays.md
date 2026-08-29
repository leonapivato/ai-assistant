# 216. The page is executed in the gate by a browser `pytest` drives, and the text layer stays

- Status: Proposed
- Date: 2026-08-29

## Context

### Nothing in this repository executes a line of the front end

ADR-0168 §10 put the browser front end here:

> **Normative.** The browser front end lives in this repository, is versioned with
> it, and ships inside the same distribution as `ai_assistant`.

and its `Alternatives considered` states the reason a sibling repository was
rejected — that it "puts the half of the system that renders model output outside
this repository's gate, review floor and ADR ledger."

The ledger and the review floor arrived with that decision. **The gate did not.**
`tests/interfaces/gateway/test_bundle.py` is 6,170 lines and collects 220 cases on
this tree, and by its own docstring every one of them reads the shipped files as
text — "Read off the shipped files rather than argued from the source." The
assets it reads are `app.js` (8,247 lines), `app.css` (619) and `index.html`
(445). The cases are substring, ordering and count assertions over those bytes.

There is no JavaScript runtime anywhere in the gate. There is no `package.json` in
this repository, no `node`, `npm` or `npx` step in the `justfile` or in
`.github/workflows/gate.yml`, and no `jsdom`, `vitest` or `jest` in any
environment this project installs. `scripts/playwright-mcp.sh` launches a browser,
but it launches it for the *coding harness* — its own header says so: "This is the
coding harness's browser, not the assistant's tool. Nothing under
`src/ai_assistant` launches this server, imports it, or hands it anything."

So the page is versioned, reviewed and ADR-governed, and never run.

### What a text assertion cannot see, with the case that found it

Issue #1707 was raised as a `Major` by adversarial review round 3 of PR #1702 and
waived there, because closing it is a repository-wide decision rather than one
page fix's to take. Its example is exact, and it is the shape of the whole gap:

> a substring assertion that `stopPlaying()` precedes `playing = mine` pins the
> *shape* of a fix and cannot distinguish a working state machine from a broken
> one that spells itself the same way.

Two lines in the right order are a fact about the file. Whether a press that
arrives *during* a five-second `decodeAudioData` starts a source afterwards is a
fact about time, and no reading of the file decides it. PR #1702 answered it, by
driving the real page in Chromium against a real `Gateway` over a seeded
`FakeAssistantEngine`, counting `AudioBufferSourceNode.start`/`.stop` and holding
the decode open. That evidence is real and it is also gone: it lives in a PR
description. Nothing re-runs it when the next change touches that code.

`.claude/agents/worker.md` asks every lane whose diff touches
`src/ai_assistant/interfaces/gateway/assets/` to drive the page by hand and record
what it saw. That instruction found three defects on PR #1385 that had passed
every check this project runs. It is worth keeping, and it is not a gate: it binds
the lane that changed the page, not the lane that broke it from `orchestration/`.

### What the text layer is good at, which is the reason it is not the answer

`test_bundle.py` is not a bad test file that a browser would replace. It is a
different instrument, and it is the better one for a large class of questions: an
enumeration in the page agreeing with `core/types.py` (it imports
`NotificationCondition`, `SpokenAudioFormat`, `RoutableOperation` and six more and
checks the page against them), a must-not-contain (`_POLICY` permits no inline
script), a derived-not-hardcoded check. Those are properties of the artifact, they
are decidable by reading it, and they are decidable in 0.11 seconds for all 220
cases. A browser would answer them slower and less directly.

The gap is one-sided: behaviour across time. That is what has no instrument at
all.

### The two shapes available, and what each costs

**(a) A node runner** — vitest or jest over jsdom, plus a Web Audio and a
`MediaRecorder` fake. It buys millisecond unit tests and per-function isolation.
It costs a JavaScript toolchain in a Python repository: a `package.json`, a second
lockfile, a node step in the local gate and in CI, and — the part that matters
most for #1707's own example — **fakes**. A hand-written `AudioContext` whose
`decodeAudioData` resolves late asserts what that fake does. The behaviour under
test is the browser's scheduling of a real `AudioBufferSourceNode`, and a fake of
it is a restatement of the author's belief about the browser, checked against
itself.

**(b) The page drive promoted into `pytest`** — the Python `playwright` package
driving Chromium against a real `Gateway` bound in-process over
`ai_assistant.testing`'s fakes, as an ordinary test module the existing `pytest`
step collects. It buys the real browser. It costs a dependency, a browser build in
CI, wall clock, and memory.

### The figures (measured, 2026-08-29, on the machine a dispatched lane runs on)

The dependency clears the wheel filter outright. `playwright` 1.62.0 publishes
`py3-none-<platform>` wheels — `playwright-1.62.0-py3-none-manylinux1_x86_64.whl`
is the Linux one — with `requires_python: >=3.10` and no ABI tag, so there is no
cp314 wheel to wait for. Installed into a clean Python 3.14.6 environment it
resolves in under a second and brings three transitive packages: `greenlet`,
`pyee`, `typing-extensions`.

The browser build is not in the wheel and is fetched separately:

| `playwright install …` | wall clock | download | on disk |
| --- | --- | --- | --- |
| `chromium` (full build + headless shell + ffmpeg) | 21.4 s | ~283 MiB | 656 MB |
| `chromium-headless-shell` (+ ffmpeg) | 10.0 s | ~117 MiB | 267 MB |

Driving it, warm, headless, in one process:

| | |
| --- | --- |
| driver start (`async_playwright()`) | 0.40 s |
| browser launch | 0.26 s (0.07 s for the headless shell) |
| first page loaded and read | 0.21 s |
| each further page thereafter | ~70 ms |
| resident set of the whole tree (python + node driver + browser) | ~570–600 MB |

The last figure is the one that constrains the design. It is a sum of `VmRSS`
across the process tree, so it double-counts pages shared between Chromium's
processes and is an upper bound rather than a true footprint — but the direction
is not in doubt, and this project has already been bitten by exactly this. Four
concurrent `just test-fast` runs took the WSL VM down twice on 2026-08-28, which
is why that recipe now holds a per-user semaphore of three slots (#1741, and the
recipe's own comment: "a run holds 3-5G"). `-n auto` is one worker per core; a
browser launched per worker would add several gigabytes to a run that is already
near the ceiling, multiplied by up to three concurrent runs. **One browser per
run, not one per core**, is therefore a constraint on this decision and not an
optimisation left to whoever writes the code.

Against that, the suite is 24,581 tests. A layer that shares one browser and
navigates ~70 ms per case is, at thirty or forty cases, a couple of seconds of
work behind a one-off ~0.9 s start.

### Why this owes an ADR at all

Two reasons, and the second is the one that makes it un-deferrable. `CONTRIBUTING.md`
→ "Dependencies & security" says "a foundational dependency needs an ADR", and a
browser is as foundational as a test dependency gets. More importantly the layer
lands inside two ratified rules about *what a gate run is*: ADR-0136 §1's anchors
require "the whole `pytest` suite", and ADR-0166 §1 defines the discharge as a run
with "no skip beyond those the suite's own conditions declare". A test module that
may or may not run depending on whether a developer has 267 MB of Chromium on disk
is a statement about both, and it is not one to make by writing a `conftest.py`.

## Decision

**We will execute the front end inside the gate, by driving the shipped page in a
real browser from `pytest`, and we will keep the text layer.**

### 1. The front end is executed, and the executor is a browser `pytest` drives

> **Normative.** The front end is executed in this repository's gate. The suite
> loads the shipped `index.html`, `app.js` and `app.css` into a real browser and
> asserts on what the page does.

> **Normative.** That execution is performed by the Python `playwright` package
> driving a Chromium build, from ordinary `pytest` modules collected by the
> existing `pytest` step. This decision introduces no JavaScript test runner, no
> `package.json`, no Node toolchain owned by the gate, and no sixth gate step.

The second clause is the choice between #1707's two shapes, and it is (b). Three
grounds, in the order they decide it.

**The subject is the browser, so the instrument is the browser.** What has no
coverage is behaviour across time, and #1707's own example — a press arriving
during a `decodeAudioData`, and whether a source starts after it — is a question
about how Chromium schedules Web Audio. A jsdom shim has no Web Audio at all, so
option (a) answers it against a fake `AudioContext` whose promise resolves when
the test author says it does. That is a test of the author's belief. PR #1702's
drive counted `start`/`stop` on the real node and is the reason we know the fix
works; the decision here is to keep that instrument and stop throwing away its
output.

**The gate stays what it is.** ADR-0010's `Remote gate` clause runs "the five
Definition-of-Done steps — `ruff format --check`, `ruff check`, `mypy`,
`lint-imports`, `pytest` — on every pull request", and adds "The steps and their
order mirror the local gate exactly, so CI is the same gate on neutral ground, not
a second, divergent one." A node runner is a sixth step in both places and a
second toolchain to keep in step. A `pytest` module is none of those: it is
collected by a command that already runs, in an environment `uv sync` already
builds.

**The cost is one dependency rather than a supply chain.** `playwright` is one
PyPI package and three transitive ones, all of which `uv.lock` already knows how
to pin. A `package.json` is a second dependency universe with its own lockfile,
its own audit story and its own upgrade cadence, for a repository whose
`CONTRIBUTING.md` says "**uv only.** The lockfile is committed; `uv sync` is
reproducible."

What (b) costs and (a) does not is stated in §5 and §6 rather than argued away: a
267–656 MB browser build that is not in the lockfile, and a layer that is slower
per case than a unit test would be.

### 2. The text layer is not replaced, and the two layers divide by what each can see

> **Normative.** `tests/interfaces/gateway/test_bundle.py` stays. No case is
> removed from it on the ground that the browser layer exists, and the properties
> it owns — enumerations checked against `core/types.py`, must-not-contain
> assertions, derived-not-hardcoded checks — stay there.

> **Normative.** The browser layer's subject is behaviour a reading of the file
> cannot decide: ordering in time, concurrency, and what one handler does to a
> resource another holds. A property decidable by reading the shipped bytes is
> asserted in the text layer and is not restated as a browser case.

The division is not a style preference; it is what keeps both layers honest. A
text assertion is fast, total and exact about the artifact — it can say that a
page contains no inline script *anywhere*, which no finite set of drives can. A
drive is the only thing that can say the page behaves. Restating one in the other
buys a slower duplicate and a second place to update, and — the direction that
actually goes wrong — porting enumeration checks into the browser layer would
trade a total assertion for a sampled one.

### 3. Where it lives, how it is marked, and what it costs the anchors

> **Normative.** The layer lives under `tests/interfaces/gateway/`, in modules
> named for the behaviour they drive, and each is marked
> `pytest.mark.integration`, as `tests/interfaces/gateway/test_gateway.py`
> already is.

> **Normative.** Each such module also carries a second marker, registered in
> `[tool.pytest.ini_options].markers`, naming it as a browser drive, so that the
> layer can be named on a command line rather than only by path.

> **Normative.** The layer is collected by an unqualified `uv run pytest` and by
> `just test-fast`. No recipe deselects it, and it therefore runs at both of
> ADR-0136 §1's anchors. It takes no exemption from them.

> **Normative.** One `pytest` run launches at most one browser process at a time,
> whether it is serial or distributed: a distributed run launches no more browsers
> than a serial one. The browser is started once and shared by every case in the
> layer.

> **Normative.** The layer's whole cost — the difference in wall clock between a
> serial `uv run pytest` over the whole suite with it and one without — stays
> under 60 seconds. Exceeding that is grounds to revisit this decision, and never
> grounds to deselect the layer from an anchor.

ADR-0179 §3 made the distributed run whole — "`just test-fast` deselects nothing
on its command line. Every test the tree declares is collected and answered" —
which is what makes the second clause simply true rather than a thing to arrange:
a module in `tests/` is in every anchor's run. Saying so explicitly is
worth the line because the tempting alternative — marking the layer as something
`test-fast` skips — would recreate exactly the hole ADR-0179 closed, and would put
the page back outside the gate under a different name.

The third clause is the WSL figure from the Context turned into an obligation.
Mechanism is left to the implementation lane: an xdist group that pins the layer
to one worker is the obvious one, and it is not ratified here because the recipe
flag it needs is that lane's to weigh. What is ratified is the property — a
`-n auto` run must not multiply ~570 MB by the core count.

The 60-second budget is chosen against the measurements: ~0.9 s to a first page
and ~70 ms per navigation puts a layer of forty cases an order of magnitude
inside it, so the budget is a tripwire for a layer that has grown into something
else, not a target to fill.

### 4. The drive is bound to a gateway over the canonical fakes, and to nothing else

> **Normative.** The page is driven against a real `Gateway`
> (`ai_assistant.interfaces.gateway.server`) bound on a loopback port in the test
> process, over `ai_assistant.testing`'s `FakeAssistantEngine` or a subclass of
> it, seeded by the test. No hub process, no model provider, no keyring, no
> network beyond loopback, and no data directory outside the test's `tmp_path`.

> **Normative.** The browser loads the bundle from that gateway and from no other
> origin. A case that substitutes the page's own assets, or opens them from a
> `file://` URL, is not part of this layer.

This is the shape `tests/interfaces/gateway/test_gateway.py` already uses, and it
is chosen for that reason rather than invented: that module binds a `Gateway` on a
free loopback port over a `FakeAssistantEngine`, under
`pytest.mark.usefixtures("hermetic_assistant_env")` so the developer's shell
cannot change a verdict, and its docstring gives the same justification — "Driven
through a real socket rather than through the object's methods, and that is
deliberate". The browser layer adds a browser to a harness that exists. Session
minting has a helper there too (`tests/interfaces/gateway/gateway_mint.py`'s
`mint_bootstrap`), and ADR-0182 §1's obligation that a bootstrap value be minted,
disclosed and only then promoted already binds any test that mints one — so
nothing new is imposed here, and the drive has no reason to reach around a helper
that exists.

The second clause is ADR-0168 §10's other normative sentence — "the page it serves
loads no asset, font, style, script or datum from any origin but the gateway's
own" — becoming something the gate *observes* rather than something
`test_bundle.py` infers from the absence of a URL in the text. A drive that
stubbed the assets would forfeit exactly that.

### 5. The dependency, and the browser build that is not one

> **Normative.** `playwright` is added to the `dev` dependency group in
> `pyproject.toml`, ranged in this file's ordinary form. It is never a runtime
> dependency, is never imported from `src/`, and no built distribution carries
> it.

> **Normative.** The layer uses `playwright.async_api` with the suite's own
> fixtures. The `pytest-playwright` plugin is not adopted.

> **Normative.** The browser build is not vendored, not committed and not in
> `uv.lock`. It is fetched by `playwright install`, which `just setup` runs
> locally and which `.github/workflows/gate.yml` runs as an
> environment-preparation step beside `uv sync --locked`. The build installed is
> the one the installed `playwright` version pins; nothing else is accepted as a
> substitute.

> **Normative.** The build installed and driven is the full `chromium`. The
> lighter `chromium-headless-shell` may be substituted for it only where the
> substituting change has established, by running this layer's own cases against
> both builds, that they agree on every behaviour those cases assert — the Web
> Audio and `MediaRecorder` paths included — and records that comparison in its
> PR. Absent that evidence the full build is what is installed, locally and in
> CI.

> **Normative.** The layer drives Chromium and no other engine. Adding WebKit or
> Firefox to it — with the install, the wall clock and the second set of
> behaviours to keep green that each brings — is not authorised by this decision
> and takes an ADR of its own.

`pytest-playwright` is declined on a mechanical ground, not a preference: this
suite is `asyncio_mode = "auto"` and the gateway harness is async, while that
plugin's fixtures are synchronous and it adds command-line options of its own to
a suite whose anchors are defined in terms of what a bare `pytest` collects
(ADR-0166 §1). Using `async_playwright` directly costs a fixture and keeps the
invocation surface unchanged.

**The install step is not a sixth gate step and does not disturb ADR-0010.** That
ADR's five steps are `ruff format --check`, `ruff check`, `mypy`, `lint-imports`
and `pytest`, and its 2026-08-22 amendment note says "It is still the same five
steps over the whole suite". `.github/workflows/gate.yml` already runs four
preparation steps before the first of them — checkout, install `uv`, install the
pinned Python, `uv sync --locked` — and the browser install belongs with those. It
prepares the environment the fifth step runs in; it asserts nothing and can fail
only as an environment failure.

**The build clause defaults to the expensive build on purpose.** The headless
shell is 10.0 s and ~117 MiB against the full Chromium's 21.4 s and ~283 MiB, and
if the page's behaviour under test runs identically on it, it is the better buy
for CI. But "runs identically" is a claim about Web Audio and `MediaRecorder`
under a stripped build, and those are precisely the paths #1707 exists for — so it
is a claim to be *tested*, by running the cases on both builds, and not one to be
assumed by whoever is trying to shave a CI step. The clause is written so that the
cheap option is available and the evidence for it is not optional, and so that
"the shell was already installed" is not by itself a reason.

**The engine clause is a refusal, and it is marked because it refuses something a
later lane could otherwise do** (ADR-0089 §1: "an ADR's declined alternatives are
marked where they refuse something a later lane could otherwise do"). The page's
ruled surface is one owner's browsers; cross-engine coverage is a different
decision with different costs, and whoever wants it argues for it on those.

### 6. Where the browser is absent the layer skips, and CI is what makes that payable

> **Normative.** Where the browser build the installed `playwright` pins is not
> present, the layer skips, with a message naming the command that installs it.
> That skip is a condition the suite declares, in ADR-0166 §1's sense, and an
> anchor discharged by a run carrying it is discharged.

> **Normative.** CI installs the browser unconditionally, so the layer runs on
> every push to an open PR and every push to `main`. A local run is never the only
> place it ran.

This is the same structure ADR-0166 §3 used, and it is taken deliberately from
there. That section made `just test-fast`'s deselection payable by naming CI as
the net — "CI runs the full serial gate on every push to an open PR (ADR-0010,
`synchronize`) … with no dependence on the agent's judgement". The same net
carries this, and for a stronger reason: a browser build is a 267–656 MB download
that a fresh clone does not have, and a layer that hard-failed without it would
turn `uv run pytest` from a command that works into a command that works after a
setup step, for every lane in this repository including the great majority whose
diff never touches the page.

Two things bound the risk honestly, and neither is a reason to think it is zero.
`just setup` installs the build, so a clone set up after this lands has it and the
skip is the exception rather than the normal case. And ADR-0136 §3 is explicit
that "A red **final** push is the failure the closing anchor exists to prevent" —
an agent that gated with the layer skipped and pushed a page regression gets a red
`gate`, discovers it at the merge rather than at the anchor, and has to rebase and
re-gate. That is a real cost, paid by the lane that skipped the install. It is
accepted because the alternative charges every lane 267 MB and 10 s to buy it.

The skip is written into ADR-0166 §1's own words rather than around them. That
clause admits "no skip beyond those the suite's own conditions declare"; this
section is the declaration, so a run in which the layer skipped for the stated
reason still discharges an anchor, and one in which it skipped for any *other*
reason does not.

### 7. This layer does not get to be flaky

> **Normative.** A case in this layer that fails intermittently is fixed, or
> removed and its gap filed as an issue, in the change that notices it. It is
> never retried, never marked `xfail` to quiet it, and no test-retry plugin is
> introduced for it.

> **Normative.** The layer waits on conditions the page exposes. A fixed sleep is
> not a synchronisation primitive here.

Stated because this is the failure mode browser suites reach, and it is worse than
having no layer: a suite with a known-flaky test trains every reader to re-run red
and teaches the gate's own verdict to mean "probably". This project has no retry
plugin and no `flaky` marker today, and this decision does not add the first one.

The second clause is where flakiness actually comes from — a drive that sleeps
200 ms and hopes is a race the CI runner will lose eventually. `playwright`'s
`expect`/`wait_for` primitives poll a stated condition, which is both the fix and
the reason the layer can be fast.

### 8. What this does not decide

One thing here is a refusal rather than a silence, so it is marked (ADR-0089 §1):

> **Normative.** This decision changes nothing about the coding harness's own
> browser — `.mcp.json`'s `playwright` server and `scripts/playwright-mcp.sh` —
> and does not discharge `.claude/agents/worker.md`'s instruction that a lane
> whose diff touches `src/ai_assistant/interfaces/gateway/assets/` drives the page
> itself and records what it saw. The existence of this layer is not a ground for
> a lane to skip that drive, and that drive is not required to use this layer.

The two browsers share a vendor's name and nothing else. One is an editor's tool
whose own header says "This is the coding harness's browser, not the assistant's
tool", sitting "where `just review-codex` sits"; the other is a test dependency in
the `dev` group. And they answer different questions: the hand-drive finds what
nobody thought to assert — it found three defects on PR #1385 that had passed
every check this project runs — while this layer re-checks what someone did think
to assert, on every push. Neither substitutes for the other, which is why the
clause is a refusal and not a note.

The rest are genuine silences:

- **Which behaviours get cases, and in what order.** That is the implementation
  lane's, seeded by #1707's `interruptPlayback`/`decodeAudioData` example and by
  #1371's three page gaps, which are exactly the shape a drive can pin and a
  substring cannot.
- **Whether the page ever gets a build step.** ADR-0168 §10 left that to "whoever
  needs one … in the change that needs it", and this decision is not that change:
  the browser loads the shipped assets exactly as served.
- **Coverage of any other interface.** The CLI and the wire client are tested as
  they are today. This decision is about the one surface that ships JavaScript.
- **Whether `test_bundle.py` should shrink.** §2 forbids deleting cases *because*
  the browser layer exists. It rules nothing about cases that are wrong, redundant
  with each other, or asserting a shape nobody decided.

### 9. What this records against earlier ADRs

Nothing is owed on any of them, and the test is ADR-0082 §1's applied to each:
"Would a reader holding only the earlier ADR now act differently, or read one of
its clauses more widely than it now holds?"

- **ADR-0136 — nothing owed.** §1 requires the full gate at two anchors, and §3's
  clauses about red pushes are untouched. This decision adds tests to the suite
  those anchors run. A reader holding only ADR-0136 runs the whole suite at each
  anchor, which is exactly right after this lands. §2's "A diff touching no file
  under `src/` or `tests/` owes no `pytest` run between the anchors" stays true
  word for word.
- **ADR-0166 — nothing owed, and §1 is relied on as written.** Its second clause
  admits a run with "no skip beyond those the suite's own conditions declare", and
  §6 above is such a declaration rather than an exception to it. No sentence of
  ADR-0166 becomes false or over-wide; a reader holding only it reads §6's skip as
  a declared condition, which is what it is.
- **ADR-0179 — nothing owed.** Its subject is the Protocol-triad check's evidence
  under a distributed run. §3's "`just test-fast` deselects nothing on its command
  line" stays true, because this decision explicitly declines to deselect anything
  (§3 above), and its clause that a distributed CI run keeps "ADR-0010's five
  steps … unchanged in number, kind and order" stays true for the reason §5 gives.
- **ADR-0168 — nothing owed, and this is the case worth arguing.** §10's two
  normative clauses are about where the bundle lives and what the page may load;
  both stay literally true and one of them (§4 above) becomes better enforced. The
  sentence a reader might think is amended is §10's non-normative "The honest cost
  is a front-end toolchain in a Python repository … nothing in milestone 13's
  behaviour requires a build step, and this ADR requires none. Whoever needs one
  pays for it then, in the change that needs it." That sentence anticipated a
  later change paying a toolchain cost; it did not decide that none would. It is
  also about a *build* step, and this decision adds none — the browser loads what
  ships. That settles it on content alone, and the form settles it again: ADR-0168
  is a marked ADR (57 clauses), the sentence carries no mark, and ADR-0089 §3 says
  of a marked ADR that "Unmarked text is read to determine what a marked clause
  *means*; it never supplies an obligation."
- **ADR-0010 — nothing owed.** Its `Remote gate` clause names five steps whose
  "steps and their order mirror the local gate exactly". After this decision they
  are still those five, in that order, in both places; the browser install is a
  preparation step beside `uv sync --locked`, of which the workflow already has
  four. Its 2026-08-22 amendment note — "It is still the same five steps over the
  whole suite" — likewise stays true.
- **ADR-0015 — nothing owed.** The review loop, the triage rule and the
  issues-over-files rule are untouched.
- **ADR-0089 — this ADR is marked**, and its clauses are the whole of its
  obligations (§3). Unmarked text here explains and does not bind.

## Consequences

**Easier.** A change to `app.js` can be shown to work rather than shown to be
spelled a particular way, by something that runs on every push. The evidence PR
#1702 produced by hand becomes a standing artifact instead of a paragraph in a
closed PR. #1371's three gaps — which conversation the next ask lands in, whether
prior turns render on resume, whether a forget shows an outcome — become
assertable, and they are the reason batch #1782 puts that issue after this lane's
implementation. The `worker.md` hand-drive keeps its job (finding what nobody
thought to assert) and loses the job it was badly suited to (regression).

**Harder.** A fresh clone needs a 267–656 MB browser before the layer runs; until
it does, the layer skips and the clone's anchors are weaker than CI's. CI's job
grows by 10–21 s of install, on a job that last measured 5m28s before ADR-0179
distributed it. The suite gains a class of test that can fail for reasons that are
not about the code — a browser that will not launch, a missing system library —
and §7 is the discipline that keeps that from becoming ambient noise. Every lane
now carries a dependency it mostly does not use.

**Follow-on work.** One implementation lane: the dependency, the marker
registration in `[tool.pytest.ini_options].markers`, the browser-launch fixture
and its one-browser-per-run constraint, the `just setup` and `gate.yml` install
steps, and the first cases — starting with #1707's own, a press over a live
playback and a press during a held `decodeAudioData`. It installs the full
`chromium` unless it does the both-builds comparison §5 requires, and it reports
the measured wall clock the layer adds against §3's budget.

**Revisit if:** the layer's added wall clock passes the 60-second budget in §3;
a `-n auto` run is observed launching more than one browser; the skip in §6 is
found to have hidden a page regression to a red final push more than once;
`playwright` stops publishing a wheel installable on this project's Python; or the
front end grows a build step, at which point the question of a node toolchain is
open again on different facts.

## Alternatives considered

- **A node runner over jsdom (vitest or jest) with Web Audio and `MediaRecorder`
  fakes.** *Rejected in §1.* It answers #1707's own example against a fake of the
  thing under test, and it buys a second toolchain, a second lockfile and a sixth
  step in two gates for a repository that has deliberately stayed on one package
  manager. Its genuine advantage — per-function isolation at millisecond cost —
  is worth less here than it looks, because the page's untested behaviour is
  cross-cutting by nature.
- **Do nothing; keep the hand-drive in `worker.md` and the text layer.** *Rejected
  in §1.* The hand-drive binds the lane that touches the page, which is the lane
  least likely to break it unknowingly, and it produces evidence with a lifetime
  of one PR. Two years of `test_bundle.py` growth has not made a substring
  assertion able to see a race.
- **Vendor or commit the browser build.** *Rejected in §5.* It is 267–656 MB of
  binary, versioned against a package that upgrades independently, in a repository
  whose one existing vendored artifact (ADR-0024) is deliberately fetched rather
  than committed.
- **Adopt `pytest-playwright`.** *Rejected in §5.* Synchronous fixtures against an
  `asyncio_mode = "auto"` suite, plus command-line options added to an invocation
  whose exact collection defines an anchor.
- **Mark the layer so `just test-fast` skips it.** *Rejected in §3.* It would put
  the page back outside the anchors under a new name, and it would undo the
  property ADR-0179 was written to establish.
- **Require the browser, failing rather than skipping when it is absent.**
  *Rejected in §6.* It charges every lane in the repository for a layer that
  concerns one subsystem's assets, and it turns `uv run pytest` in a fresh clone
  from a working command into a failing one.
