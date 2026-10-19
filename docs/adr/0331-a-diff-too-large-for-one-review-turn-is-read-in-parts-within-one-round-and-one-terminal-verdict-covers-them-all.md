# 331. A diff too large for one review turn is read in parts within one round, and one terminal verdict covers them all

- Status: Proposed
- Date: 2026-10-19
- Scope: how `scripts/codex-review.sh` hands a committed diff to the reviewer when the diff does not fit one turn, and what a recorded review then attests. Tracker: #3176, the pull request whose rounds could not start.
- Dependency: ADR-0020, ADR-0025, ADR-0027 and ADR-0209, as their status lines leave them.
- Authorization: the dispatcher assigned 0331 and posed the question. The owner has not ruled on any design here. This ADR recommends one and records the others under "Alternatives considered". Ratifying it is the owner's act, after reading it (§1).
- **Amends and supersedes nothing.** §10 applies ADR-0070 §1's test to each decision this one touches, and no record is written onto any of them.

## Context

### The question

A review round sends the reviewer one prompt, and that prompt carries the whole diff. When the diff
is larger than the reviewer can take in, the round never starts. This ADR decides how a change that
large gets its required reviews, without weakening what a recorded review attests (ADR-0025,
ADR-0027) and without touching what `scripts/ship.sh` accepts.

### What the driver does today

`scripts/codex-review.sh` builds each round's prompt in `_write_prompt`. The prompt holds any
re-injected dispositions (ADR-0025 §1's mechanism b), then the persona rubric, then the ADR-0020 §1
preamble that classifies the changed paths. After that comes the whole `base_sha...content_sha`
diff, verbatim, in one fenced `diff` block. The diff is rendered with the pinned `_diff_opts`, so
these are the bytes `patch_identity` hashes. The instruction reads "Review ONLY the committed diff
below … You may read full files in the repo for context". Every round is one `codex exec`
invocation: a fresh read-only session in round 1, a resume of the persona's thread after that. Its
final message is the artifact.

No ADR says the diff must be inlined whole. ADR-0027 §2 does rest the patch identity on that
practice: the identity must move when "a base move *into* the region the diff touches changes the
content the reviewer read". So the identity stands for the content that was put in front of the
reviewer.

### What failed on #3176

#3176 implements ADR-0328: 134 files, +10,249 / −13,019 lines. Both lenses' round 1 died before any
review happened. The architecture round failed with
`turn/start failed: Input exceeds the maximum length of 1048576 characters`, `"actual_chars":1704691`.
The adversarial round failed the same way at 1,704,846. Measured on the branch against its merge
base, the rendered diff is 1,700,075 bytes: `src/` 786,388, `scripts/` 11,555 and `tests/` 902,132.
At `-U0` it is still 1,473,185.

Cutting that lane further does not get it under the limit. A contract triad with its primary
production implementation is one unit of work (ADR-0137 §2, ADR-0328 §1:3). The type change breaks
every caller at once, and the lane's tests alone are 0.90M characters. ADR-0328 §1:4 does let §14's
removals land ahead of the type change, which would shrink this one diff. It would not answer the
question, which comes back with every large contract change. So this is a capability the review
loop lacks, not a lane that was cut wrong.

### Codex's input limit is not the only one that binds

The 1,048,576-character limit is a hard refusal at turn start. A second limit binds well below it,
and it does so silently. The evidence comes from the Codex session rollouts on the operator's
machine (`~/.codex/sessions`, 2026-02-21 to 2026-10-19, codex-cli 0.162.1). Together they hold
2,614 review prompts, which are the turn prompts `_write_prompt` built.

- **The context window is 258,400 tokens.** Every rollout that records it records that figure
  (`model_context_window`). A large diff prompt runs at about 3.7 to 3.9 characters per token: a
  628,967-character prompt took 168,779 input tokens on its first call, and a 958,168-character one
  took 247,918.
- **Codex compacts a turn when its context fills.** The earliest compaction after a review prompt
  came at 203,992 input tokens. The reviewer's own reads move a turn toward that line. Across 784
  rounds that never compacted, those reads added 57,714 tokens at the median, 101,529 at the 75th
  percentile and 138,753 at the 90th.
- **Compaction keeps a turn's prompt whole only up to about 254,000 characters.** In all 487
  compactions that followed a review prompt, that prompt survived whole when it was 254,046
  characters or shorter, which happened in 285 of them. It was cut when it was 254,868 or longer,
  in the other 202. A cut prompt keeps its head and its tail. The 958,168-character prompt above
  compacted straight after its first call and came out at 255,059 characters: the rubric, then the
  last part of the diff. For the rest of that turn, the middle 700,000 characters of the diff
  existed only as Codex's encrypted summary.

So the diff "in front of the reviewer" is guaranteed to stay there for a whole turn only up to about
254,000 characters. Above that, today's single-turn round shows the reviewer every byte once, at
its first call. A compaction then takes part of the diff away while the review is still running,
and nothing records that it happened. Of the 2,614 review prompts, 543 (20.8%) were over 240,000
characters. None was over 1,048,576 until #3176.

### What the reviewer can read for itself

The reviewer runs commands in the repository under the read-only sandbox, and that includes `git
diff`. The rollout `rollout-2026-10-18T22-17-01-01a151f2-af89-73d1-b395-cab0e95dd34c.jsonl` records
`"sandbox_policy":{"type":"read-only"}`. In that turn the reviewer ran
`git diff bc74b6ac… 6f8175a8… -- deploy/container/build.sh .github/workflows/container.yml`, which
exited 0 and returned the patch. The same output also carries
`Warning: truncated output (original token count: 13559)`, because Codex shortens a long tool
result before the model sees it. So a read works, and the reviewer chooses each one. A long read
comes back through a window that can shorten it, and nothing records which hunks the reviewer
actually paged through.

### What the ratified texts already fix

- **One conversation per loop and persona.** It starts read-only in round 1 and is resumed after
  that, and re-injection plus a plain cold review are the floor when it is lost (ADR-0025 §1).
- **A finding is retired only by Codex's own updated assessment** (ADR-0025 §2).
- **The shippable artifact is the conversation's terminal verdict.** Its disposition snapshot is
  selected by the full anchor, read-only is proven rather than assumed, and verdict-changing
  evidence reaches the merge reviewer (ADR-0025 §4).
- **Coverage is anchored on the patch identity of the whole rendered diff** (ADR-0027 §2), and an
  artifact is named by the fields it is selected by (ADR-0027 §6).
- **The live disposition mechanism infers retirement from absence.** `_write_snapshot` marks a
  finding `retired` when a later round stops raising it. ADR-0043, which would have replaced that
  inference with explicit markers, is `Withdrawn` and binds nothing.
- **ADR-0020 rejected "a hard round cap or diff-size threshold"** as a way to stop a review loop.
  The threshold below stops nothing: every hunk is still reviewed.
- **`scripts/codex-review.sh` is a standing review contract**, so any change to it binds every open
  lane holding a recorded review when it merges (ADR-0209 §1).

## Decision

We will keep the round's shape: one persona, one conversation, one terminal verdict and one
artifact per reviewed tree. What changes is how the diff reaches the reviewer when it does not fit
one turn. Under the turn budget, a round is exactly today's. Over it, the driver splits the diff it
already renders into parts that each fit. It puts each part in front of the reviewer, verbatim, in
a turn of its own within the same round, and keeps each turn's findings outside the model's
context. A final verdict turn sees all of those findings and closes the round, and its output is
the round's artifact. `scripts/ship.sh` reads that artifact unchanged.

### 1. Status and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` → "Finishing
> an ADR PR" requires have returned green on one tree and the owner, having read it, has authorized
> its ratification. An assigned number or a green review alone does not change its status.

> **Normative.** This decision is built by its own lane after it merges `Accepted`, and by no lane
> before. That lane changes `scripts/codex-review.sh` and its tests under `tests/scripts/`.

> **Normative.** No lane changes `scripts/ship.sh`, `docs/review/**` or the artifact's format in
> order to build this decision.

### 2. Terms

- **The rendered diff** is `git diff <base_sha>...<content_sha>`, rendered with the pinned
  `_diff_opts`. It is the byte sequence a round's patch identity is computed over.
- **A turn prompt** is everything the driver hands Codex in one invocation.
- **A single-turn round** is today's round: one turn prompt carrying the whole rendered diff.
- **A parted round** is a round that reads the rendered diff in **parts**, one **part turn** per
  part, and then closes with one **verdict turn**.
- **An attempt** is one run of the driver for one persona on one reviewed tree, from its first
  turn to the artifact it records or to its failure.

### 3. The turn budget

> **Normative.** The turn budget is 240,000 characters. No turn prompt in a parted round exceeds
> it, counting the rubric, the preamble, the part or the collected findings, the
> instructions and any re-injected dispositions.

> **Normative.** The driver measures a prompt against the turn budget by a count that is never
> lower than the prompt's length in characters. A count of UTF-8 bytes qualifies.

The figure comes from the Context. 240,000 characters is 14,046 under the largest prompt a
compaction was seen to keep whole, so a part survives a compaction mid-turn. It is about a quarter
of Codex's hard limit. At roughly 3.7 characters per token, it leaves about 135,000 tokens below the
earliest compaction seen for the reviewer's own reads, which is more than the 75th percentile of
what reviewers read in practice. A lower figure buys nothing more, and only adds turns. A higher
one gives up the guarantee that a part stays whole.

### 4. Under the budget, nothing changes

> **Normative.** A round runs as a single-turn round, exactly as before this decision, when the
> prompt `_write_prompt` builds for it, without re-injected dispositions, fits within the turn
> budget. Its prompt, its injection budget and its degradation floor (ADR-0025 §1) are all
> unchanged.

Re-injection can still push a single-turn round's prompt over 240,000 characters. That is today's
behaviour, and it stays bounded by the existing injection budget, which keeps the prompt about half
the hard limit. It is left alone so that "under the budget, nothing changes" holds byte for byte.

### 5. Over the budget, the diff is read in parts

> **Normative.** A round whose prompt would not fit the turn budget under §4 runs as a parted
> round.

> **Normative.** A parted round's parts are cut from the rendered diff in the order git emits it.
> Consecutive whole file entries are packed into one part while that part's turn prompt fits the
> turn budget.

> **Normative.** A file entry that does not fit a part turn by itself is split only between its
> hunks, and every piece carries the entry's header lines. No hunk is ever split.

> **Normative.** Every hunk of the rendered diff appears in exactly one part. With the repeated
> header lines removed, the parts concatenated in order reproduce the rendered diff byte for byte.

> **Normative.** A parted round's parts are a function of the rendered diff and the turn budget
> alone, so every persona reviewing one tree reads the same parts.

> **Normative.** Each part turn carries the persona rubric, the ADR-0020 §1 preamble for the whole
> change with every listed path marked by the part that carries it, the instructions below, and its
> own part verbatim. Every changed path is listed once, not twice.

> **Normative.** Before its first turn, the driver checks the whole partition. A parted round
> fails before any turn starts, and records nothing, when the turn budget cannot hold a part
> turn's fixed content (the rubric, the marked preamble and the instructions) together with one
> hunk, or together with one file entry that has no hunk. The driver prints what did not fit, its
> size, the fixed content's size and the turn budget.

That change, or what did not fit, has to be cut. With a few thousand changed paths, the marked
preamble alone can approach the budget. At 240,000 characters, a hunk that does not fit would be
several thousand lines of one file with no three unchanged lines anywhere in it.

> **Normative.** Each part turn tells the reviewer four things: that it is reviewing part *i* of
> *k*; that it may read anything in the repository, including another part's hunks by `git diff
> <base_sha> <content_sha> -- <path>` with the pinned SHAs written out; that it reports findings in
> `docs/review/guide.md`'s format; and that it writes no verdict.

> **Normative.** A parted round's turns run in part order. Off the bypass path, they run in the
> persona's one conversation (ADR-0025 §1): in round 1 the first part turn starts that
> conversation, and in a later round it resumes it.

> **Normative.** Off the bypass path, every turn of a parted round runs read-only, and the driver
> proves it for every turn from Codex's own record, as ADR-0025 §4 requires of a round. One
> unproven turn fails the round, and it records nothing.

> **Normative.** The driver captures each part turn's final message verbatim, outside the model's
> context, and keeps it in `.review/` beside the artifact the round records.

### 6. One verdict turn closes the round

> **Normative.** A parted round's verdict turn carries the persona rubric, its instructions, and
> every part turn's captured message from the same attempt, verbatim and in part order.

> **Normative.** No part turn's captured message is truncated or dropped from the verdict turn.
> When those messages alone do not fit the turn budget, the round fails and records nothing.

> **Normative.** In a parted round, re-injected dispositions (ADR-0025 §1's mechanism b) ride in
> the verdict turn. When they would push it over the turn budget, they are dropped whole, which is
> ADR-0025 §1's floor.

> **Normative.** The verdict turn reports the ranked findings and the one-line verdict that
> `docs/review/guide.md` requires. Its final message is the round's artifact body, and the
> disposition snapshot is written from it (ADR-0025 §4). No other output of the round becomes
> either one.

> **Normative.** The driver never merges, dedupes, rewrites or drops a finding. Which part findings
> the verdict holds is the reviewer's own assessment in the verdict turn (ADR-0025 §2).

> **Normative.** The verdict turn is told to name, in its output, every part finding it no longer
> holds, with its reason. That way a finding dropped within a round reaches the record the merge
> reviewer reads (ADR-0025 §4).

> **Normative.** The driver re-checks HEAD and the working tree after every turn of a parted
> round. If either has changed, the round fails and records nothing, as a single-turn round does
> when the check fails at its end.

> **Normative.** A failed turn fails its attempt: no artifact, no snapshot, and no newly recorded
> thread. A later attempt's verdict turn carries only that attempt's own part messages.

### 7. What a recorded review attests

For a single-turn round, nothing changes.

> **Normative.** An artifact recorded by a parted round attests two things. First, every hunk of
> the rendered diff was put verbatim in front of that persona's reviewer in exactly one turn of the
> round, whose whole prompt fit the turn budget. Second, its findings and verdict are the round's
> terminal turn, given over every part turn's captured message.

It does not attest that the reviewer held the whole diff in view at once. No round over about
254,000 characters has had that property past a compaction. With the turn budget at 240,000
characters, every turn of every round now keeps its whole prompt through a compaction. Today's
single-turn rounds above that size do not.

> **Normative.** A parted round records the patch identity of the whole rendered diff, computed
> exactly as a single-turn round's is. No part has an identity of its own, and no acceptance path
> accepts or refuses an artifact part by part.

ADR-0027 §2's premise is kept, not restated. The identity stands for the content put in front of
the reviewer during the round, and a parted round puts all of that content in front of it, hunk by
hunk. Paths (a) and (b), the floor and the drift disclosure apply to the artifact as they always
have. A parted round's artifact is one artifact per persona per tree, named as ADR-0027 §6 names
any artifact.

### 8. Every lens, every path

> **Normative.** This decision applies to every persona. Each persona reads the parts in its own
> conversation, and a both-lens round stays one round.

> **Normative.** On the bypass path, each turn of a parted round is a cold invocation made exactly
> as that path makes its one invocation today: no session, no sandbox and no read-only proof. The
> verdict turn's inputs are still exactly those §6 lists.

Nothing about coverage or the verdict rests on what the conversation remembers. The verdict turn
receives every part's findings verbatim, so the persistent session's memory helps a parted round
without being relied on.

> **Normative.** A parted round counts as one round in ADR-0020 §2's aggregate, because it records
> one artifact per persona for one tree. The driver's printed output names the number of parts.

### 9. The reads this decision relies on

> **Normative.** No part of a round's coverage rests on a read the reviewer chooses to make. Reads
> stay what the instruction has always offered: context.

The reviewer can read another part's hunks from the repository, and does so under the read-only
sandbox, as the Context records. A read can come back shortened and leaves no record of what was
read, and that is why coverage is placed on the turn prompts. Reads supply context for a finding
that spans parts. The verdict turn is where a finding that spans parts is settled.

### 10. Relationship to earlier decisions

ADR-0082 §1 has this text apply ADR-0070 §1's test: would a reader holding only the earlier text
now act differently?

- **ADR-0025 §1** is kept. A parted round is several turns of the persona's one conversation, which
  starts read-only and is resumed as §1 says. Mechanism (b) and its floor apply in the verdict turn
  (§6). A reader holding ADR-0025 alone resumes the same thread and keeps the same records.
- **ADR-0025 §2** is kept. The driver retires nothing, and the verdict turn's choices are the
  reviewer's.
- **ADR-0025 §4** is kept. The verdict turn is the round's terminal turn, its output is the
  shippable artifact, and the snapshot comes from it. Off the bypass path, read-only is proven for
  every turn. A part finding the verdict turn drops reaches the merge reviewer (§6). The snapshot
  stays selected by the full anchor, because there is still one artifact per anchor.
- **ADR-0027 §2 and §6** are kept (§7).
- **ADR-0020 §1** is kept, because every part turn carries the preamble. **§2** is kept, because a
  parted round is one round. **§3** is kept as ADR-0027 left it. The rejected "diff-size
  threshold" is a different thing: the turn budget changes how a diff is delivered and stops no
  review.
- **ADR-0209 §1** is kept. This decision adds no path to the floor and removes none. Its
  implementation changes `scripts/codex-review.sh`, so when that lane merges, it binds every open
  lane holding a recorded review, as any change to that file does.
- **ADR-0138** and **ADR-0243** count reviewed trees, and a parted round records one, so both
  counts are unchanged.
- **ADR-0043** is `Withdrawn`, and nothing here depends on it.

> **Normative.** This decision amends and supersedes no clause of any other ADR, and writes no
> record onto any.

### 11. What the implementation lane owes

> **Normative.** The implementation lane's tests show that a round under the turn budget builds a
> prompt byte-identical to the one built before this decision.

> **Normative.** The implementation lane's tests show that a parted round's parts, with repeated
> headers removed, reproduce the rendered diff, and that no part turn prompt exceeds the turn
> budget.

> **Normative.** The implementation lane's tests show that a parted round fails before any turn is
> invoked when one hunk does not fit beside a part turn's fixed content, and when the fixed content
> leaves no room for one file entry that has no hunk.

> **Normative.** The implementation lane's tests show that a parted round records nothing when any
> turn fails, when any turn's read-only proof fails, or when HEAD or the working tree changes
> between turns.

> **Normative.** The implementation lane's tests show that a parted round on the bypass path makes
> every turn as a cold bypass invocation, and records its artifact without a read-only proof.

> **Normative.** The implementation lane's tests show that the verdict turn carries every part
> message verbatim, and drops re-injected dispositions, never part messages, when the turn budget
> requires it.

The tests run against a stubbed `codex` as the existing `tests/scripts/` suites do. No test
contacts the service.

## Consequences

- **#3176 can be reviewed.** At 240,000 characters it reads in about eight parts and one verdict
  turn per lens. Any later large contract change can be reviewed the same way, with no refusal and
  no cut that ADR-0137 §2 forbids.
- **What an artifact attests gets stronger above about 254,000 characters, not weaker.** Today a
  round that size shows the reviewer the whole diff for one call, and can then lose the middle of
  it to a compaction without any record. Under this decision, every hunk stays whole in front of
  the reviewer for its whole turn.
- **It costs turns, and more rounds than #3176 pay that cost.** A parted round pays for *k* + 1
  turns per lens instead of one. On the record in the Context, about one review prompt in five was
  over 240,000 characters, and each of those rounds would become two or more part turns plus a
  verdict turn. Wall time per round grows with it, so `just review-codex-wait` answers "still
  running" more often.
- **Cross-part reasoning is weaker than having everything in view at once.** A part turn sees the
  others only through the marked preamble, its own reads and the conversation's compacted history. The
  verdict turn sees every part's findings, but not every part's hunks. This is the main cost in
  review quality, and it is carried deliberately.
- **The constant is a measurement of one Codex version and one model.** Revisit it, by a new ADR,
  when a Codex upgrade moves the context window, the compaction retention or the hard input limit.
  Revisit the design if a parted round misses a defect that spans parts and a single view would
  have caught it.
- **The implementation binds open lanes when it merges** (ADR-0209 §1), as every change to the
  driver does.

## Alternatives considered

- **P: inline the code and pull the tests.** The dispatcher leaned this way. Over a threshold, the
  prompt would inline every hunk outside `tests/`, list each changed test path with its line
  counts, and tell the reviewer to read those hunks from the repository. One artifact, and no
  change to `ship.sh`. Rejected for three reasons. First, the tests' coverage would rest on reads
  the reviewer chooses, through a tool window that can shorten them, with no record of which hunks
  it read. The artifact would then attest weaker coverage for tests than for code, and ADR-0027
  §2's premise would have to be restated to mean "made available" for half the diff. Second, it
  fails the case it exists for. On #3176 the inlined part alone is about 0.80M characters, roughly
  210,000 tokens. That is past the earliest compaction at the first call, and more than three
  times what a compaction keeps whole. So the code would be cut mid-turn, and the tests would be
  read into a context that is already full. With its threshold set where a prompt stays whole, P
  refuses #3176 outright. Third, "tests" is a class of paths, not a size, so any code change larger
  than the threshold still refuses.
- **S as briefed: review each part as its own review.** Each part would get its own turn or
  session per persona, the loop would be green only when every part is green on one tree, and
  `ship.sh` would require every part. This gives full inline coverage, but it changes the artifact
  model, the session shape, the snapshot selection and `ship.sh`'s acceptance, which is ADR-0025
  §§1 and 4 and ADR-0027 §6 territory. This decision keeps S's partition and folds the parts back
  into one round with one terminal verdict, so none of that moves.
- **The same design with the budget just under the hard limit, about 900,000 characters.** Far
  fewer rounds would change, and the extra turns would be paid almost only by changes the size of
  #3176. But every round between about 254,000 and 900,000 characters would keep today's silent
  loss at compaction, and each of #3176's parts, at about 900,000 characters, would itself be cut
  mid-turn. This is the alternative to choose if the owner weighs cost above that guarantee: only
  the constant in §3 changes.
- **Shrink the diff: fewer context lines, or deletions elided.** `-U0` is still 1.47M characters
  on #3176. Eliding deleted lines hides what a removal removed, which a reviewer needs to judge.
  Either way, what the reviewer reads would no longer be the rendered diff the identity hashes.
- **Refuse, and require the change to be cut.** Rejected. It leaves a triad with its primary
  implementation unreviewable, against ADR-0137 §2's unit of work, and the refusal would come back
  with every large contract change.
