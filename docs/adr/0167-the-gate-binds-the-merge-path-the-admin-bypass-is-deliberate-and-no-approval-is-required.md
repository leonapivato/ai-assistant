# 167. The gate binds the merge path, the admin bypass is deliberate, and no approval is required

- Status: Proposed
- Date: 2026-08-20

## Context

ADR-0010 decided how work integrates on GitHub, and one clause of its Decision —
headed "**Branch protection (pragmatic)**" — enumerates four settings for the
protected branch:

1. the `gate` status check required before merging, "enforced for **everyone,
   with no bypass**";
2. "one approving review";
3. the branch **up to date** before merging, and **linear history**;
4. administrators **not** included "in the review/up-to-date restrictions,
   leaving an escape hatch for a genuine solo emergency".

Its 2026-07-19 amendment restates the same list as carried over unchanged
through the `master` → `main` rename.

**Three of the four are not what the repository runs, and have not been for
months.** Read from the API on 2026-08-20:

```console
$ gh api repos/{owner}/{repo}/branches/main/protection
  "required_status_checks":       {"strict": true, "contexts": ["gate"]}
  "required_pull_request_reviews": {"required_approving_review_count": 0,
                                    "dismiss_stale_reviews": false,
                                    "require_code_owner_reviews": false,
                                    "require_last_push_approval": false}
  "enforce_admins":               {"enabled": false}
  "required_linear_history":      {"enabled": true}
  "allow_force_pushes":           {"enabled": false}
  "allow_deletions":              {"enabled": false}
```

`enforce_admins` is GitHub's "do not allow bypassing the above settings" toggle,
and it is **off** — which exempts repository administrators from every protection
above it, the required `gate` check included. `required_approving_review_count`
is **0**, not one. Only item 3 is configured as ADR-0010 ratified it.

**Why the divergence arose is not carelessness.** ADR-0010 asked for a *split*:
the gate binding administrators, administrators exempt from the review and
up-to-date restrictions only. Classic branch protection cannot express it. The
administrator exemption is one all-or-nothing toggle, not a per-rule one, so
whoever configured the repository had to pick a side — and picked the escape
hatch ADR-0010's own item 4 asked for, at the cost of item 1's "no bypass".

**The approvals divergence has a separate cause and a ruling behind it.** On
2026-07-29 the owner ruled that approving reviews are no longer required: with no
second author to ask, an approval was a self-approval, and the pre-merge bar is
the Codex review reported by `just ship` plus the `gate`. `CONTRIBUTING.md` →
"Working on GitHub" has documented that as settled ever since. No ADR recorded
it, so ADR-0010's item 2 stayed ratified against a repository that had stopped
doing it.

Issue #1246 found all of this while checking a CONTRIBUTING sentence about the
`--admin` bypass, and found the sentence **true** and the ADR stale. It put two
options to the owner: tighten the settings to match ADR-0010, or record the
configuration and supersede the clause. **The owner ruled the second on
2026-08-20**, and this ADR is that record.

## Decision

**We will record the branch protection this repository actually runs as the
decision, and retire the part of ADR-0010's clause that describes something
else.** No setting changes with this ADR: the configuration quoted above is the
configuration ratified below.

### 1. The protection on `main`, as configured and as ratified

> **Normative.** The `main` branch stays protected so that a merge requires a
> pull request, the `gate` status check green, and the branch up to date with
> `main`; the branch keeps linear history and admits neither force-pushes nor
> deletions.

That is items 1 (in its status-check half) and 3 of ADR-0010's clause, unchanged
in effect, plus the pull-request requirement ADR-0010 decided in its
"Pull-request integration" clause. `required_pull_request_reviews` being present
at all is GitHub's "require a pull request before merging" toggle switched on, so
the PR path is required even at zero approvals — the count governs how many
approvals that PR needs, not whether a PR is needed.

This section re-states rather than re-decides: a reader who acted on ADR-0010's
item 3 acts identically after this ADR, which is why §5 leaves that item standing
rather than replacing it.

### 2. The `gate` binds the normal merge path; the conduct rule binds the other one

> **Normative.** Every merge on the normal path — a pull request, the only path a
> lane uses — requires the `gate` check green on content that is up to date with
> `main`.

> **Normative.** Nothing crosses the gate red. An administrator bypass is never
> used to merge a pull request whose `gate` is failing, whatever the flag
> mechanically reaches.

ADR-0010's item 1 said one thing about two levels, and they come apart here. As a
statement about the **mechanism** — "enforced for everyone, with no bypass" — it
is false of this repository and is replaced. As a statement about **conduct** it
is exactly right and is carried forward verbatim in the second clause above: the
gate is the reason to trust a merge, and a bypass that can mechanically reach it
is not licence to use it for that.

This is the same reading `CONTRIBUTING.md` has been applying since PR #1265
recorded the divergence beside its bypass paragraph; what changes is that the
conduct rule now has an ADR that also describes the mechanism correctly, instead
of one that asserts a mechanism the repository does not have.

### 3. `enforce_admins` is false, deliberately

> **Normative.** `enforce_admins` stays disabled on `main`, and the administrator
> bypass it leaves open is retained as the repository's escape hatch.

> **Normative.** The bypass is reached for only when the check standing in the
> way is **stale** rather than failing — a branch `strict` is holding because it
> is behind `main` — and the reason goes in the pull request.

This is a posture, not a tolerated defect. The repository has one administrator,
who is also its only merger and the person the lock would restrain; the threat
model is trusted-single-operator, the same boundary the ruling on #1262 disposed
of as a class. The owner's ruling on #1246 records that the bypass has never been
used to merge a red `gate`.

What the escape hatch buys is the case ADR-0010's own item 4 named: a merge that
is genuinely stuck for a reason the checks cannot resolve. What it costs is that
the mechanism cannot enforce §2's conduct clause against the one person able to
break it — which is why §2 states that clause as conduct and this section states
its blast radius plainly rather than implying a guarantee.

### 4. No approving review is required

> **Normative.** `required_approving_review_count` stays 0. The pre-merge
> independent judgement on a change is the Codex review `just ship` reports, not
> a GitHub approval.

ADR-0010's item 2 required one approving review, in a repository that then had
two contributors. It has one author of record and a fleet of dispatched lanes,
and a required approval would be the author approving their own merge — a
ceremony that produces a green tick and no judgement. The 2026-07-29 ruling
retired it; this section is that ruling written where a decision belongs.

Nothing about the *evidence* a merge carries is relaxed by this. ADR-0015's
review loop is unchanged, `just ship` still refuses to post a review that does
not cover the PR head's content, and `gate` is still required.

### 5. What this replaces in ADR-0010, and what stands

This ADR **partially supersedes** ADR-0010, and its authoritative extent
(ADR-0070 §4) is this:

**Replaced — the "Branch protection (pragmatic)" clause's administrator-bypass
and approving-review bullets.** Item 1's "enforced for **everyone, with no
bypass**" (as a claim about the mechanism; §2 keeps the conduct half), item 2's
"one approving review", and item 4's exemption of administrators from "the
review/up-to-date restrictions" — which is not the exemption the repository has,
the toggle being all-or-nothing. §§1–4 above put the configured posture in their
place.

**Replaced — the settings-change route to tightening.** ADR-0010's Alternatives
says the repository "can tighten to strict if the team or the blast radius grows
— a settings change, not a new ADR", and its Consequences names the same
tightening under a Revisit clause. That route is gone: `enforce_admins: false` is
now a ratified decision rather than an unrecorded configuration, so reversing it
reverses a decision.

> **Normative.** Enabling `enforce_admins` on `main` takes an ADR superseding
> this one (ADR-0070 §1); it is no longer a bare settings change.

**Standing, untouched.** Item 3 — up to date before merging, linear history — is
configured as ratified and re-stated in §1. ADR-0010's "Remote gate" clause, its
"Pull-request integration" clause and its "Merge method" clause (rebase-and-merge
only) are not touched by this ADR at all, nor is anything in its 2026-07-19
amendment beyond that note's restatement of the superseded bullets, which is read
through them.

**The record on ADR-0010.** Its `Status` takes the leading-token form ADR-0070 §4
requires of a new partial supersession, and the record itself goes in an appended
dated note — ADR-0082 §2, which puts an amendment record in the note alone on a
line led by `Partially superseded by`, and ADR-0070 §1, under which a dated header
note and a landed-supersession `Status` edit are both permitted in place. No
ratified sentence of ADR-0010 is rewritten.

**Why a superseding ADR and not an in-place amendment.** ADR-0070 §1's test comes
out one way only: a reader holding ADR-0010 alone believes the gate is
mechanically unbypassable and that their PR needs an approval. Both change how
they act. That is a change to what was decided, so it takes a new ADR.

### 6. The revisit condition

> **Normative.** If the repository gains a second person able to merge, or merge
> rights are delegated to anyone else, §3's ruling is re-opened and
> `enforce_admins` reconsidered.

The whole argument for the bypass is that the only person it exempts is the
person every other control already trusts. A second merger falsifies the premise
directly, and ADR-0010's own Revisit clause named "the team grows" first for the
same reason. This is not a schedule — nothing expires — but it is the specific
fact that re-opens it, and it is stated so a later reader does not have to
reconstruct which fact mattered.

## Alternatives considered

- **Option A: set `enforce_admins: true` and keep ADR-0010 as ratified.**
  Declined by the owner on #1246, on two grounds. The only person the lock
  restrains is the sole administrator and merger, so it buys enforcement against
  the one party the repository already extends full trust to. And the ADR-0165
  residual it would close — the exempt ratification commit is unreviewed by
  construction, with CI as its enforcement point, and an administrator can
  bypass CI — is inside the class the ruling on #1262 disposed of deliberately,
  as a documented residual, for exactly this threat model. It also costs the
  escape hatch entirely, since the toggle is all-or-nothing: a genuinely stuck
  merge would need the protection temporarily relaxed, which is a worse act than
  the bypass it replaces.
- **Amend ADR-0010 in place.** Rejected under ADR-0070 §1: the correction changes
  what a reader acts on (§5), so it is a supersession however small the edit
  would have been.
- **Migrate to GitHub repository rulesets to express ADR-0010's split.** Rulesets
  carry bypass actors per ruleset, so the split ADR-0010 wanted — gate binding
  everyone, PR and up-to-date rules bypassable — is likely expressible by
  splitting the rules across two rulesets. Not taken: after §3 the split is no
  longer what this repository wants. The bypass is ratified as covering the gate
  too, on the trusted-operator argument, so there is nothing left for the
  migration to buy, and changing the protection mechanism is a larger act than
  the ruling authorised.
- **Leave the record where PR #1265 left it — CONTRIBUTING describing an open
  divergence.** Rejected: that was the right holding action for a lane whose
  fence excluded decisions, and it is not a resting place. A living document
  cannot be the record of a decision (ADR-0001), and the standing text tells a
  reader the question is unruled, which stops being true with this ADR.

## Consequences

- The ADR corpus and the repository agree about branch protection for the first
  time since 2026-07-29, and `CONTRIBUTING.md`'s bypass paragraph can state a
  settled rule with a citation instead of an open divergence pointing at #1246.
  That edit rides with this ADR.
- The bypass is now documented as *deliberate* rather than merely *present*. A
  reader who reaches for `--admin` gets §3's two clauses — the stale-check case
  it is for, and §2's flat refusal on a red gate — instead of ADR-0010's promise
  that they could not be there at all.
- Tightening got more expensive on purpose: it costs an ADR rather than a
  toggle. That is the intended trade for the setting being a decision, and §6
  names the fact that makes it worth paying.
- The gap between conduct and mechanism stays open, and is stated rather than
  closed. §2's second clause is enforced by nothing but the operator's own
  discipline. If an incident ever shows it was not enough, §6's revisit and
  option A above are the response — and that incident is precisely the evidence
  ADR-0010's Revisit clause asked for.
- Nothing else moves. No settings change, no code, no other ADR: ADR-0136's
  gate anchors, ADR-0165's flip shape, ADR-0027's review-coverage rule and
  ADR-0015's review loop all read the same before and after.
