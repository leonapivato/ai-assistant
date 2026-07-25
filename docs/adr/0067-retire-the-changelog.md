# 67. Retire `CHANGELOG.md`

- Status: Accepted
- Date: 2026-07-25
- Supersedes: ADR-0003 §"Documentation"'s `CHANGELOG.md` clause. Every other
  clause of ADR-0003 — including §"Versioning" — is unchanged. See
  "Relationship to ADR-0003 and ADR-0019".

## Context

`CHANGELOG.md` was ratified by ADR-0003 §"Documentation" as part of the initial
standards package: "decisions recorded as ADRs from `docs/adr/template.md`;
`CHANGELOG.md` in Keep a Changelog format." It has been maintained by hand ever
since, by whichever agent happened to be finishing a change.

**It stopped, and nothing noticed.** The file was last written on 2026-07-22 by
commit `2955914`, the commit that ratified ADR-0034; ADR-0034 is the highest ADR
it names. Since that commit, measured at `e6558f4` — the state of `origin/main`
this decision was written against — the trunk has taken 262 commits and ratified
31 further ADRs, ADR-0036 through ADR-0066, no ADR-0035 having been issued, over
four days. None of them appears in the file, and the file does not say so. It
still opens with "All notable changes to this project are documented here",
carries no marker that it fell behind, and ends in an `### Added` section whose
last entry describes work from three days earlier. A reader consulting it today
is told, in the present tense, something that is 31 decisions out of date.

**It was never a release record.** Checked across every revision of the file in
git history, exactly one version heading has ever existed in it: `## [Unreleased]`.
There has never been a dated release section, there are no git tags,
`pyproject.toml` is at `0.1.0`, and neither `.github/workflows/gate.yml` nor the
`justfile` has a publish step. The project is perfectly *installable* — it
builds a wheel and an sdist and `uv sync` installs it — but no version of it has
ever been **published**, so there is no released version anyone could be
upgrading from, and no consumer outside this repository. The audience a
changelog is written for — someone choosing between two published versions,
wanting to know what changed between them — does not exist yet.

**It had already decayed internally, before it stopped.** Under the single
`[Unreleased]` heading, Keep a Changelog's own structure had broken down:
`### Added` appears three times, `### Fixed` twice, `### Changed` twice, in no
order. And the file carried a factually false claim about system behaviour — it
asserted that every candidate failure in the router was logged, when a
non-routable failure is deliberately not logged. That is now pinned by
`tests/models/test_routing.py::test_a_non_routable_failure_is_deliberately_not_logged`,
whose comment records the changelog as the source of the overclaim. The edit
that corrected it left a duplicated word ("every every") in the sentence, which
has sat there unread since.

**Three other records already carry this history, and none of them has to be
written separately from the work it describes.**

- **ADRs** (ADR-0001): dated, numbered, and append-only. A **substantive
  contract ADR** — ADR-0015 §5's scope, "one adding or changing a Protocol or a
  `core/` type crossing subsystem boundaries" — additionally "ships as its own
  PR, ratified before the implementation PR that depends on it"; trivial ADRs
  (amendments, status changes, supersessions) are exempt there. Every other
  decision, this one included, lands with the change it authorises. Either way a
  decision is in `docs/adr/` by construction, not because someone remembered to
  write it down a second time.
- **Commits** (ADR-0003): one logical change each, with a Conventional Commit
  subject whose *format* a `commit-msg` hook enforces. The commit log is
  therefore already a change log, at finer granularity than the file offered.
  The `Refs: ADR-NNNN` trailer linking a commit to its decision is a convention
  and not a checked one — `git log --grep` finds what carries it, and
  `docs/adr/` rather than the trailer is the authority on what was decided.
- **Merged PRs and their review artifacts** (ADR-0015 §1, ADR-0027): every change
  carries an independent review of its diff, recorded under `.review/`, which
  `ship` refuses to post without.

The changelog was a fourth, hand-maintained copy of what those three already
hold, and the only one of the four that had to be authored separately from the
change it described — so the only one that could silently stop. It failed the
way ADR-0015 §"Hand-maintained coordination state decays exactly when it
matters" said a hand-maintained file in git fails: not by being obviously
abandoned, but by staying plausible while going wrong.

## Decision

**We will retire the `CHANGELOG.md` convention and delete the file.**

**1. The convention is retired.** No change is required to describe itself in a
changelog. What a change was and why is carried by its commit message, by its
ADR where it records a decision, and by its PR.

**2. The file is deleted, not frozen behind a retired header.** The alternative
— keeping it in place with a "retired, superseded by ADR-0067" banner — was
considered and rejected on three grounds:

- Git retains every entry verbatim and forever. `git show 2955914:CHANGELOG.md`
  reproduces the file exactly as it last stood, dated, attributed, and adjacent
  to the tree it described — which is strictly more context than a frozen copy at
  the repository root would carry. This ADR is the pointer to it.
- A file named `CHANGELOG.md` at the root of a repository is read as the current
  record of change, by humans and by tooling, largely regardless of what its
  first paragraph says. Its content is 31 ADRs stale and contains at least one
  behavioural claim already found false. A banner asks a reader to override a
  filename convention with a paragraph — an invariant enforced by prose rather
  than by mechanism, which ADR-0015 found does not hold here.
- ADR-0015 §4 set the precedent and the reasoning. `TODO.md` and `WORKING.md`
  were **deleted**, not annotated, because a hand-maintained state file in git is
  a surface, and the fix for a surface is to remove it rather than to label it.

A freeze buys a reader nothing git does not already give them, and costs the one
thing deletion guarantees: that stale content cannot be mistaken for current.

**3. ADR-0003 §"Documentation"'s `CHANGELOG.md` clause is superseded.** Nothing
else in that section moves — Google-style docstrings, "comments explain why", and
recording decisions as ADRs all stand. ADR-0003 §"Versioning" is untouched: SemVer
and a single version source in `pyproject.toml` remain the rule. So does
ADR-0003's Consequences observation that declining to auto-generate
versions/changelog from commits keeps tooling simple — that is now the whole of
the position rather than half of it. Per ADR-0001, ADR-0003's status line records
the superseded clause and its body is left unedited.

**4. The living documents are corrected to name what actually holds the history.**
`CONTRIBUTING.md` §"Versioning" and `VISION.md`'s two pointers ("what has shipped
is recorded in `CHANGELOG.md`", and the Related-documents entry) are amended. A
retired convention that `CONTRIBUTING.md` still instructs agents to follow is not
retired. No workflow, `just` recipe, `pyproject.toml` entry, or issue/PR template
referenced the file, so nothing mechanical is removed by this change.

**5. Historical mentions inside ratified ADRs are left alone.** ADR-0003 §40,
ADR-0019 §0 and §"Relationship to ADR-0003" describe what was true when they were
written and remain correct as history (ADR-0001 append-only, ADR-0019 §4).

**6. What replaces it if the project ships is not decided here.** See
Consequences.

## Relationship to ADR-0003 and ADR-0019

ADR-0003 is the decision this one supersedes a clause of, because ADR-0003 is what
required the file.

ADR-0019 is the harder one, and it has to be answered by name rather than stepped
around. **ADR-0019 §0 names `CHANGELOG.md` explicitly and exempts it** from the
no-state-claims rule: it "fails the second [living-document property]: its entries
are dated releases read as history." Its §"Relationship to ADR-0003" then lists
"`CHANGELOG.md` format" among the ADR-0003 clauses it leaves standing. That is the
strongest available argument against retiring the file.

**The exemption is sound as written, and its premise is not satisfied by the file
it names.** The ground of the exemption is *dated releases*. An entry under
`## [1.2.0] — 2026-08-01` carries a timestamp and is read as history, which is
exactly what puts it outside ADR-0019's reach. This file has never had one. Every
entry, in every revision of it, from its first commit to its last, sits under
`## [Unreleased]` — a section that is:

- **undated and continuously revised in place**, which is ADR-0019 §0's first
  property, and
- **read as currently authoritative**, which is its second — stated outright by
  another document, since `VISION.md` instructed the reader that "what has
  shipped is recorded in `CHANGELOG.md`".

An open `[Unreleased]` section is a living document wearing a changelog's
filename. So this ADR does not carve an exception out of ADR-0019. It observes
that ADR-0019's exemption never covered the artifact as built, and that the
artifact is the thing ADR-0019 §1 forbids: a claim that a body of work is
finished, written into an undated document, owned by no check, decaying from the
moment it was written. The 31 unrecorded ADRs are that decay, arriving on
precisely the schedule ADR-0019's own evidence predicted — its motivating example
was a test count that was wrong on the day it was written.

**ADR-0019 is not amended and its status does not change.** §0 states a rule that
follows from two properties and lists `CHANGELOG.md` as an application of it.
Removing the artifact removes the application; the rule and the dated-release
exemption survive intact, and would govern a future per-release changelog on
arrival exactly as §0 says — which is the shape decision 6 leaves open.

## Consequences

**What is lost.** The project no longer has a human-readable, prose summary of
user-facing change that is independent of commit archaeology. This is the real
cost of the decision and it should not be talked down. Someone asking "what
changed between these two points, in prose, without reading 262 commits" is now
left with `docs/adr/`, which is organised by decision rather than by release and
written for an implementer, and `git log`, which is organised by commit. Neither
is a substitute for release notes. Two things make the cost acceptable rather
than free: there is nobody downstream to ask the question, since no version has
ever been published; and the file was not answering it anyway, having been
three days and 31 ratified decisions behind at the moment it was deleted. Also
lost is the Keep a Changelog vocabulary (Added/Changed/Fixed/Removed/Security) as
a shared shape for describing change; Conventional Commit types cover
approximately the same ground at commit granularity.

**What stands in for it if the project ever ships to users — a future decision,
not this one.** A release needs release notes, and whoever ratifies the first
release decides what they look like. The material will be there: ADRs are dated
and numbered, and each commit is one logical change with a typed subject, so
notes for a tagged range can be *assembled at release time* from
`git log <prev>..<tag>` rather than maintained continuously between releases.
Assembling them may well want the `Refs: ADR-NNNN` link to be reliable rather
than conventional, which is a check to decide on then, alongside the release
format itself. ADR-0003's Consequences already noted
that Conventional Commits "leave that door open later"; this ADR narrows nothing
about it. Whatever form it takes, ADR-0019 §0 constrains it: it must be a
**dated, per-release** artifact, not an open `[Unreleased]` section — the absence
of that dating is why this file failed.

**What becomes easier.**

- One fewer hand-maintained file in git, and therefore one fewer merge-conflict
  surface for concurrent agent lanes — ADR-0015 §4's reasoning, applied to a
  file of the same kind.
- The record has one authority per question: decisions in `docs/adr/`, change in
  `git log`, review in `.review/` and on the PR. Previously a fourth, unchecked
  copy could disagree with all three, and did.
- No agent spends part of a change writing a second description of it that no
  check will ever read.

**What would trigger revisiting.** The project acquiring an installable release
and consumers of it. At that point the question is not "reinstate this file" but
"what does a release note look like here", answered under decision 6 and
ADR-0019 §0. Reinstating a continuously-maintained `[Unreleased]` section
specifically would need new evidence that hand-maintained prose state can be kept
current in this repository — evidence this file's history is against.
