# Proposals

A **proposal** is a design under discussion, before anyone has decided it. It
is a Markdown file in this directory on a branch, opened as a **draft pull
request**, and it never merges as a proposal: when the owner accepts it, the
same file is rewritten into the ADR that decides it; when the owner declines
it, the pull request is closed unmerged. `CONTRIBUTING.md` → "A proposal is a
draft PR that becomes its ADR" is the rule; this file is the working guide.

Nothing in this directory on `main` is a proposal. A file here on `main` is a
guide like this one, or a mistake.

## Why here, and not the wiki or an issue

The [wiki](https://github.com/leonapivato/ai-assistant/wiki) describes the
system's design at a high level: what the ratified decisions describe, and the
owner's direction where it goes further. A proposal works a design out in
detail against that baseline, so it cites wiki pages and never lives among
them; the one time proposals were kept as wiki pages, the page and the issue
recording the same design disagreed within a week.

An issue records the ruling and links the work, but a thread is a poor place to
read a design: the current text is buried under its own history, diagrams do
not render, and there is no diff. A pull request gives the proposal a
rendered, versioned text, review threads anchored to lines, and a diff
against every earlier version.

The ADR corpus is where decisions live, and an ADR is expensive to write for a
reason: a number, marked normative clauses, citations in form, append-only once
merged. A proposal is the cheap stage before that cost is worth paying.

## Writing one

```bash
git fetch origin
git switch -c proposal/<slug> origin/main
$EDITOR docs/proposals/<slug>.md
git add docs/proposals/<slug>.md
git commit -m "docs(proposals): <what it proposes>"
git push -u origin proposal/<slug>
gh pr create --draft --title "proposal: <what it proposes>"
```

The file has no fixed template. What a useful one carries:

- **The question** it answers, in one sentence at the top.
- **The baseline**: the wiki pages describing what it changes, each linked
  with the wiki revision read, and the ADRs whose clauses it would touch.
- **The change**, written as a diff against that baseline: what a reader of
  those pages would find different afterwards. Mermaid diagrams render on the
  pull request; use them.
- **Options considered**, with their tradeoffs, where the choice is open.
- **What it leaves open**, named, so a reader can tell a gap from an omission.

Write it in prose. A proposal carries **no ADR number, no `- Status:` line and
no marked normative clauses**; those are the ADR's, and adding them early makes
the file look decided before it is.

## While it is open

The pull request is the medium. Rewrite the file in place and push; the pull
request's history is the record of how the design moved, and review threads on
the diff are where it is discussed. Where an issue already tracks the topic,
link the pull request from it and keep the ruling there; the text stays in the
pull request.

An open proposal authorizes nothing. It does not claim scope, block a lane,
or amend an ADR, and no implementation cites it. Work that needs the decision
waits for the ADR.

Neither of ADR-0136's gate anchors arrives while it is a draft proposal:
no review is invoked on it, and it is never flipped out of draft as a
proposal. So no review round and no full-gate run is owed until conversion,
not as an exemption but because the events that oblige them have not happened.

## When it is decided

**Accepted.** On the same branch, move the file to `docs/adr/NNNN-<title>.md`
and rewrite it into the ADR form (`docs/adr/template.md`): Context, Decision
with every ruling marked, Consequences, citations in ADR-0088's forms, `- Status:
Proposed`. The number is assigned at conversion by whoever dispatches ADR work
(`CLAUDE.md` → golden rule 5); do not pick one. Keep the proposal's argument
where the template wants it (Context, and the rejected alternatives), and drop
the rest. From here the branch is an ADR pull request and
`CONTRIBUTING.md` → "Finishing an ADR PR" applies unchanged: the full gate, the
adversarial review (and the architecture review for a contract surface),
`just adr-ratify`, `just ship`, `just ready`, merge. The proposal file does not
survive the conversion commit.

**Declined.** Close the pull request unmerged with the ruling in the closing
comment. The branch keeps the text; nothing on `main` records it except the
issue, if one exists.

**Parked.** Close the pull request with a comment pointing at the issue that
holds it, and note the branch name there so the text can be reopened.

A proposal that was accepted and whose ADR later proves wrong is withdrawn or
superseded as any ADR is (`docs/adr/template.md`); it is not reopened as a
proposal.

## After the ADR merges

Nothing here owes a wiki edit. The wiki is the owner's medium, not a step of
this process: a page is updated when the owner brings it up or someone next
edits it, and its sources then record the decision's status. Until then a
page's inspected revision is the reader's warning that it predates the change.
