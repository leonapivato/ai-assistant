# NNNN. <short title of the decision>

- Status: Proposed | Accepted | Withdrawn | Superseded by ADR-XXXX | Partially superseded by ADR-AAAA (<scope>) [and ADR-BBBB (<scope>)]…
- Date: YYYY-MM-DD

<!-- Use "Partially superseded by ADR-XXXX (<scope>)" when a later ADR replaces
only part of this one: the supersession leads and "Accepted" is dropped (so a
prefix match on "Accepted" cannot misread the replaced part as live), and the
parenthesis names exactly what was replaced. The remainder stays accepted. If a
further ADR later replaces a different part, add its pair on the same line —
"Partially superseded by ADR-A (<scope-a>) and ADR-B (<scope-b>)" — without
dropping the first. See ADR-0070 for the amend-vs-supersede test and ADR-0001 for
the append-only rule.

Use "Withdrawn" — the bare token, nothing after it — for a proposal that was
merged "Proposed" and then ruled against rather than ratified. It is available
from "Proposed" alone, it is terminal, and the same change appends a dated header
note giving the date, the authority and the ground; a bare "Withdrawn" with no
such note is not a withdrawal. The document, its number and its text stay in the
corpus and stay citable for what they say. Withdrawing an ADR that is already
"Accepted" is not permitted — that is a change to what was decided, so it takes a
superseding ADR. See ADR-0127.

A header note this ADR writes onto an earlier ADR does not state this ADR's
status: it may say the change takes effect on this ADR's ratification, and says
nothing further about whether that has happened. A note saying this ADR "remains
Proposed" goes stale the day it is ratified, where ADR-0165's one-line flip
cannot reach it (ADR-0277 §3). -->


## Context

<The forces at play: the problem, constraints, and what makes this a decision
worth recording. Neutral — describe the situation, not the answer.>

## Decision

<The decision, stated in the active voice: "We will ...". Be specific enough
that someone can act on it without asking follow-ups.>

<!-- Mark every ruling. A clause is normative when a reader could disobey it —
it constrains what an implementation, a lane, or a later ADR may do. A
measurement, an argument, a worked example, or a classification of this change
is not, however load-bearing it is (ADR-0089 §1). The form is a block quote at
column 0, preceded by a blank line, containing no fenced block, stating one
obligation — a passage stating two separable obligations is two clauses (§2):

`> **Normative.** <one obligation, with its scope, conditions and exceptions.>`

To *show* a mark rather than make one — quoting another ADR's ruling, exhibiting
the form — put it inside a fenced block: a `**Normative.**` line inside a fence
is display, not a mark (§2). A quotation of another ADR's marked clause carries
no `**Normative.**` token: fence it, or block-quote it without the token
(ADR-0277 §3). A quoted mark is a second clause this ADR never ruled, and the
citation check fails one whose text equals another ADR's marked clause.

Name one ruling by its clause identifier, `ADR-NNNN §S:k`: the k-th marked clause
of ADR-NNNN within section S, where S is the nearest numbered heading's label
(`5`, `10a`) or, with none in its level-2 section, that heading's first word
(`Context`); `§S:j-k` names a range, and several may share one prefix after
commas (ADR-0277 §1). The citation check fails one naming a clause that does not
exist, and `just adr-rules NNNN` prints an ADR's clauses under their
identifiers.

Mark every obligation you mean to impose, because the marks are the whole of
them: in a marked ADR, unmarked text is read to determine what a marked clause
*means* and never supplies an obligation, so a rule stated only in the prose
beside a mark binds nothing (§3). An ADR that marks nothing is unmarked and
binds as prose, exactly as the ratified corpus does — marking is forward-only,
and nothing already ratified is marked (§5). An ADR numbered above 0277 that
marks nothing fails the citation check unless it is Withdrawn (ADR-0277 §2).

Cite in ADR-0088 §1's three forms, never with a line number (ADR-0088 §5):
name the symbol, and quote the line where the position matters.
`CONTRIBUTING.md` → "Cite in form, and mark what binds" states both decisions
for a reader who is not reading these ADRs. -->

## Consequences

<What becomes easier and what becomes harder as a result. Include follow-on work
and anything that would trigger revisiting this decision.>
