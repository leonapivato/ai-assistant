"""The observer's two prompts, declared (ADR-0329 §9, ADR-0334 §2).

The scout's and the commit step's instructions are templates (ADR-0334): each system
message is rendered from a file shipped beside this module, ``observer_scout.txt`` and
``observer_commit.txt``, or from the owner's override of it, which the composition root
reads at start and hands :class:`~ai_assistant.orchestration.observer.stage.Observer`
(§3:5). This module declares them and keeps no copy of their text (§3:1). Each declares
one flag and no value: :data:`PERSON_FLAG`, true exactly where the observer holds a
person-model store and the leaving episode is a person's, so its step is given that
person's five fields and may answer what ADR-0338 §9 lets it (§9:1-§9:5). Where it is
false, as on every hub whose ``Settings.person_model`` is off, each instruction renders
as it did before the flag, and no new output is read. The user message each step sends
is one JSON object the stage renders (``reading`` and ``commit``), and every value in it
is quoted source data under ADR-0098 §2; that stays in code, whatever a template says
(§1:3).

What an instruction says is guidance to a model. What must hold whatever a model
answers is held by code instead: origins, ``when``, source details and who added a
support (§9:5); that every part resolves in a stored episode (§9:5); the evidence
floor (§11:5); the admission of the assistant's own words (§10:1); and that a finding
comes from the leaving episode (§8:2). The instructions say those rules too, so a
model's decision usually passes the checks, but no check trusts them, and no template
changes them (ADR-0334 §7:2).
"""

from __future__ import annotations

from typing import Final

from ai_assistant.core.prompts import PromptDeclaration

__all__ = ["OBSERVER_COMMIT_PROMPT", "OBSERVER_SCOUT_PROMPT", "PERSON_FLAG"]

#: Where both defaults ship: beside this module (ADR-0334 §3:1).
_PACKAGE: Final = "ai_assistant.orchestration.observer"

#: Both prompts' one flag (ADR-0334 §4:2): the step is given the leaving episode's
#: person's five fields (ADR-0338 §7:4, §9:1), and may answer what §9:2-§9:5 let it.
PERSON_FLAG: Final = "person"

#: The scout's prompt (ADR-0329 §9:1): one call proposing findings over what §8 names.
#:
#: **What the instruction must say**, which binds the default and every override alike
#: (ADR-0334 §7:1), and which a promotion's review reads it against (§7:3): that it
#: proposes findings, each one claim naming the parts it rests on, from a candidate or the
#: record alone (ADR-0329 §9:1); that each comes from the leaving episode, a later one
#: only correcting or qualifying it (§8:2); what is kept, a request to remember or a
#: correction always (§11:1-§11:3), and that a single observation is still proposed as
#: evidence (§11:4); that a source's report is worded as what the source said (§9:8);
#: one finding per reliance where the later episodes show how it went (§14:1-§14:2); and
#: that the assistant's own words are never evidence about the user and silence is not
#: confirmation (§10:1-§10:2). That every value of the message is quoted source data, and
#: who said something is stated by the keys around it, is ADR-0098 §2's. Under
#: :data:`PERSON_FLAG`, also: that ``person`` holds the person's own current choices, not
#: set where null (ADR-0338 §3:1, §3:9); that a finding which only restates one of them is
#: marked as restating it and is not kept as a memory (§9:3); and that a suggestion names
#: a field, a value and the one part of the leaving exchange it rests on, and changes
#: nothing (§9:2).
OBSERVER_SCOUT_PROMPT: Final = PromptDeclaration(
    name="observer_scout", package=_PACKAGE, flags=frozenset({PERSON_FLAG})
)

#: The commit step's prompt (ADR-0329 §9:3, §9:4): one call per finding.
#:
#: **What the instruction must say**, which binds the default and every override alike
#: (ADR-0334 §7:1), and which a promotion's review reads it against (§7:3): that it
#: decides from what it is shown alone (ADR-0329 §9:3); the wording, the supports and
#: each one's direction, backing, how sure, about-when and note, and which operation
#: applies or that nothing is kept (§9:4); the keep rules and the bar on a memory at
#: inference alone (§11:1-§11:8); that a source's report is worded as what the source
#: said (§9:8); when an observer's inference is given (§9:7); that the user's yes is kept
#: in the words approved (§5:5); a re-check (§13:1); the track record (§14:2); and that
#: the assistant's own words are never evidence about the user and silence is not
#: confirmation (§10:1-§10:2). That every value of the message is quoted source data, and
#: who said something is stated by the keys around it, is ADR-0098 §2's. Under
#: :data:`PERSON_FLAG`, also: that ``person`` holds the person's own current choices
#: (ADR-0338 §3:1, §3:9); whether the memory the action creates or adds supports to, as
#: worded, states how the person wants to be spoken to, a request about the present
#: exchange alone not being one (§5:4, §9:4); and whether it matters in every
#: conversation, which only suggests a pin (§9:5).
OBSERVER_COMMIT_PROMPT: Final = PromptDeclaration(
    name="observer_commit", package=_PACKAGE, flags=frozenset({PERSON_FLAG})
)
