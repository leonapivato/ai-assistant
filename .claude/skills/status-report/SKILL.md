---
name: status-report
description: Report the state of dispatched work to the owner — what needs their ruling, what merged, what is in flight, what it is costing, and where the batch sits in the plan. Use when the owner asks how things are going, when a batch reaches a milestone, or when a lane stops on a decision only the owner can make.
---

# status-report

Runs whenever the owner needs to know where the work stands — on request, when
a batch closes, or when a lane stops on something only they can rule. It reports
state that `pre-dispatch-survey` and `dispatch-agents` produced; it does not
decide scope, adjudicate an escalation, or merge anything. Those loops are
elsewhere and this one only tells the owner what they did.

The audience is the **owner**, who rules and adjudicates but does not run the
loop (`CONTRIBUTING.md`). They will read from the top and may stop early, so the
section order below is part of the contract, not a suggestion: the decision they
owe comes before the progress they do not have to act on.

The report is a **message**, never a file in the tree. In-flight state lives in
the tracker (ADR-0015), and a committed status document would be exactly the
undated state claim ADR-0019 forbids — right when written, silently wrong a day
later. Commands here are illustrations for an operator, not an implementation.

This is a dev-process tool for building `ai-assistant` itself, not a product
feature.

## 1. Every claim comes from a query, not from recall

This rule governs the eight sections after it. A report assembled from what the
session remembers is a report about **the session**, not about the repository —
and the two diverge exactly where it matters, because a lane that merged, a PR
that went red, or an issue someone else closed leaves no trace in your context.

- **Every section names its evidence source.** Not in a footnote; in the
  sentence, or in the row. "Lane 3's PR is green (`gh pr checks 991`)" is a
  claim the owner can re-run. "Lane 3 is nearly done" is not a claim at all.
- **Memory and conversation context are hypotheses to verify.** They are useful
  for knowing *what to query* — which PR numbers, which batch issue, which lanes
  were dispatched — and worthless as the answer. `dispatch-agents` §3 says this
  of a worker's report; it is no less true of your own recollection, which was
  written down by the same process and has been stale longer.
- **Pin what can be pinned; timestamp what cannot.** `origin/main` resolves to a
  commit, and every read of the *tree* can come from that one commit. GitHub
  state does not work that way: `gh pr list`, `gh pr checks` and `gh issue list`
  are separate live calls with no common snapshot, and a PR can merge between two
  of them — which is how a report calls a lane in flight in one section and
  reports checks for a head that has already landed in the next. So collect the
  GitHub reads close together, record the clock time you took them, and present
  them as a reading taken *then* rather than as one atomic state. Where a fact is
  load-bearing — a lane you are about to describe as blocked in §3 — re-query
  that one immediately before sending, the way `pre-dispatch-survey` re-scans
  before it posts.
- **State the baseline in the report.** "Since when" defaults to the moment the
  batch issue `pre-dispatch-survey` opened, unless the request names another
  window ("since yesterday", "since the last report"). Say which one you used —
  the owner cannot check a delta whose start they cannot see.

```bash
git fetch origin
surveyed="$(git rev-parse origin/main^{commit})"   # pinned; the tree reads use it
observed="$(date -u +%FT%TZ)"                     # the GitHub reads below are not
baseline="$(gh issue view <batch> --json createdAt --jq .createdAt)"

gh pr list --state all --limit 200 \
  --json number,title,state,isDraft,mergedAt,headRefName,mergeStateStatus
gh issue list --state all --limit 200 --search "created:>=${baseline%T*}" \
  --json number,title,state,createdAt
gh pr checks <n>                      # per open PR — not the worker's report
gh issue view <batch> --comments      # the batch's own record
```

**Set `--limit` explicitly on both list commands**; both default to 30, so an
older open item silently falls off the page and reads as absent. **If either
returns exactly the limit, treat the list as truncated** — page with `gh api
--paginate` or raise the limit until the count comes back short. A report that
says "no new issues" from a truncated scan is worse than one that says nothing.

The one section exempt from this rule is §6, and it is exempt because it is
fenced as judgement and says so. Nothing else is.

## 2. Headline

One or two sentences, first: the **overall state**, the **single most important
thing**, and **whether anything needs the owner**. The test is that the owner
can stop reading after it and be roughly right about all three.

Write it last, from the assembled sections, and print it first. If it will not
compress into two sentences, the report has not reached a conclusion yet — go
find it rather than promoting the difficulty to the owner. A headline that
hedges across every lane ("several lanes are in various states") has spent the
owner's most-read sentence saying nothing.

## 3. Needs your ruling

**This is the first substantive section, before progress.** The owner's scarcest
contribution is a decision, and a decision they have not seen is blocking work
right now in a way that merged work never is. Progress reads well and can wait.

**When there is nothing, say "Nothing needs your ruling" in those words.**
Silence is ambiguous — the owner cannot tell "no decisions are outstanding" from
"you forgot to ask," and the second has happened. The explicit sentence is the
whole value of the section on a quiet report.

Each item is a **decision brief**, in this shape:

- **(a) The decision, as one question** — yes/no, or A/B. Stated before any
  background. If it takes three questions to state, it is three items or it is
  not yet a decision.
- **(b) Each option's concrete implications** — what merges, what stays blocked,
  what it costs in rounds, rework, or discarded work. Concrete: name the PRs and
  the lanes, not "some delay."
- **(c) Your recommendation, and why.** You hold the context the owner does not;
  making them re-derive it wastes the asymmetry the dispatch model exists for. A
  brief with no recommendation is an unfinished brief.
- **(d) What is stalled until answered, versus what proceeds regardless.** This
  is what tells the owner how fast to answer, and it is the part most often
  omitted. "Nothing stalls; this only changes the next batch" is a legitimate
  and useful answer.

**No lane jargon without a one-line gloss.** Floor path, churn ratio, triad,
drill, patch identity — these are the loop's vocabulary, and the owner rules
decisions without running the loop. Gloss it in the sentence where it appears or
rewrite the sentence; a decision the owner has to decode is a decision they
answer late or by trusting you blindly, and both defeat the purpose of asking.

**A worker's STOP already carries its proposed resolution** (`worker.md`), so
carry that in rather than re-deriving one — it is usually the recommendation in
(c), and where you disagree, say which authority overrules it
(`dispatch-agents` §4). A FLAG is not a ruling request; it belongs in §4 or §9
unless you disagree with it, in which case it has become one.

**Surface a pending decision through a channel that reaches the owner when they
are not watching, and do it before your own session ends.** A ruling that waits
for them to happen to read a transcript adds their entire away-time to the
batch's latency, and that is the one cost in this loop no amount of parallelism
recovers. The responsibility is the reporting session's, because at that moment
it is the only actor that exists:

- **The harness's push notification**, where the operator has it enabled — the
  report reaching their device is what turns an unread transcript into a prompt.
- **A comment on the batch issue** carrying the decision brief. This is the
  durable half and worth doing regardless: it outlives every session, it is where
  in-flight state already belongs (ADR-0015), and whoever picks the batch up next
  reads it there rather than reconstructing it.

Be plain about the limit rather than promising past it. Once every session has
exited, nothing is running to chase a ruling — which is the argument for pushing
*and* writing the decision down before the reporting session exits, not for
assuming some later session will notice it.

## 4. Progress since the baseline

Three groups, each queried, in this order:

- **Merged** — one line each, and the line says **what it bought**, not what it
  was called. A PR title is a changelog entry; the owner wants what the system
  can do now that it could not at the baseline, or what stopped being possible.
  Where a merge bought nothing user-visible (a process change, a test fix), say
  that plainly rather than inflating it.
- **In flight** — a lane table: **lane, PR, state, next action, who waits on
  whom**. The dependency column is the one that cannot be reconstructed from
  GitHub, and it is the one the owner uses to judge whether the batch is
  actually parallel.
- **Not started** — lanes in the batch issue with nothing open. Say *why* for
  each: waiting on a merge, waiting on a ruling in §3, or not yet briefed. A
  lane silently missing from the report reads as finished.

| Lane | PR | State | Next action | Waits on |
| --- | --- | --- | --- | --- |
| gate cadence | #991 | ready, green | merge | — |
| worker docs | #992 | draft, 1 blocker open | worker triaging | #991 (floor) |

**Every state in that table has a query behind it.** `isDraft`,
`mergeStateStatus`, and `gh pr checks` are facts; "nearly done" and "should land
today" are forecasts, and if you want to make one, it goes in §6 where it is
fenced. `BEHIND` in particular is worth reporting as itself: it says the branch
is not current with its base and owes a rebase before it can merge, and **nothing
beyond that**. A lane that rebased, gated and reviewed exactly as it should goes
`BEHIND` the instant another lane merges ahead of it, which a merge order makes
routine rather than exceptional (`worker.md`). Report the rebase it owes, not an
inference about whether it was ever gated.

## 5. New issues since the baseline

Every issue opened in the window, **each with a triage verdict**:

- **parked-fine** — real, not now, no plan needed. The default for a nit or a
  pre-existing debt a lane noticed in passing.
- **should-enter-next-batch** — it wants a lane, and you would brief one.
- **needs-ruling** — the verdict itself is the owner's, and **this promotes the
  issue into §3** as a full decision brief. Labelling it here and leaving it
  here is not enough; §3 is where the owner looks for what they owe.

**Never present an untriaged list.** A bare list of issue numbers transfers the
triage to the owner, which inverts the division of labour the whole dispatch
model rests on — they ruled that you would slice and they would adjudicate.
Triage is cheap for you (you read the diff that produced it) and expensive for
them.

Cover both what you filed and what the lanes filed: a worker's report names its
issue numbers (`worker.md`), and those are claims — verify each one exists and
says what the report says it says. An issue that was never filed is the most
common way a deferred finding disappears.

## 6. Feeling — judgement, not evidence

Its own section, under its own heading, explicitly fenced. What belongs here:

- **Convergence smell** — whether a loop reads like it is closing or circling,
  ahead of the numbers in §7 confirming it.
- **Comparisons to prior runs** — this batch against the shape of previous ones.
- **Unease with no query behind it** — a brief that felt thin, a lane whose
  reports read more confidently than its diff justifies, a decision you would
  like to revisit and cannot say why.

That last one is the reason the section exists. It is often the earliest signal
available and there is no query that produces it, so a report with no place to
put it either drops it or launders it into the fact sections as adverbs — and
**that is what makes a report unfalsifiable.** Once judgement is mixed in, the
owner cannot tell which sentences they can check, so they either check all of it
(and the report saved them nothing) or none of it.

Say what would change your mind, or what would confirm it. A fenced hunch with a
named test is actionable; a fenced hunch without one is at least honest.

## 7. Risks & burn

The finite, invisible resources — the ones that run out without warning because
nothing displays them:

- **Review quota is finite and invisible.** It is probed by a review run's own
  aggregate output, **never remembered**: a remembered quota state is wrong by
  the time it is read, and an operator top-up restores it silently. Report what a
  run actually printed, or report that it was not probed. "Quota is fine" with
  nothing behind it is precisely the sentence this section exists to prevent.
- **Per-lane round counts and churn ratios**, from the aggregate each review run
  prints. A churn ratio far above 1 means the loop is reworking itself rather
  than converging (`CLAUDE.md`), and a lane cannot see that from inside — the
  outside view is yours.
- **Anything approaching a limit**: a long-lived lane's context, clone
  availability against the number of lanes you want next, or a window about to
  close — a quiet period with no floor-touching lane open is a resource, and it
  is spent the moment two of them are.

Name the number and its source, or say it was not measured. An unmeasured
resource reported as fine is the failure mode; an unmeasured resource reported
as unmeasured is a fact the owner can act on.

## 8. Grand scheme

Where this batch sits in its leg, the leg in its arc, and how much of the leg's
**exit condition** is satisfied — quoted from the roadmap or the ADR that states
it, with which parts are met and which are not. Not a percentage: an exit test
is a set of clauses, and "60% done" hides which 40%.

**Read the plan off the surveyed commit, not off memory.** Scope lives in
`docs/roadmap.md` and the ADRs (`pre-dispatch-survey` §2), and the plan changes
by ratification without telling your context. This is also why no leg, arc, or
current-plan fact is written into this skill: a living document carries rules,
never a snapshot of what the plan currently is (ADR-0019), and a snapshot here
would rot while still reading as authoritative.

Then two things the owner cannot get anywhere else:

- **What the next dispatch would be**, in a sentence or two, offered as a
  proposal. Scope is the owner's; a proposal they can approve or redirect is
  useful, a decision presented as settled is not.
- **Drift from the plan, said plainly.** If the batch has moved away from the
  leg's exit test, or a leg is being satisfied incidentally by work aimed
  elsewhere, say so here in the fact sections — drift is a comparison between the
  ratified plan and the tree, which is checkable, and it does not belong in §6
  with the hunches.

## 9. Provenance

Close with two short lists: **what you verified directly**, and **what you took
on a worker's word**.

The default is that a worker's claim is unverified until you ran the check
(`dispatch-agents` §3), so this section is mostly a record of which checks you
actually ran. What is cheap to verify has no excuse to be second-hand: CI status,
the file list against the fence, the `ship:$sha` tag, draft state, and whether a
filed issue exists. What is legitimately second-hand: that the gate ran locally
before the push, a worker's reasoning about a finding it waived, and anything it
says it did **not** do — none of which leaves an artifact you can query.

Marking the boundary is what lets the owner calibrate the rest of the report. An
unprovenanced report is read as entirely verified, so a single second-hand claim
that turns out wrong discredits every other sentence in it — including the ones
you did check.
