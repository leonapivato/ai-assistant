"""The observer's three prompts, declared (ADR-0346 §10, ADR-0334 §2).

The scout's, framing's and placement's instructions are templates (ADR-0334): each system
message is rendered from a file shipped beside this module, ``observer_scout.txt``,
``observer_framing.txt`` and ``observer_placement.txt``, or from the owner's override of
it, which the composition root reads at start and hands
:class:`~ai_assistant.orchestration.observer.stage.Observer` (§3:5). This module declares
them and keeps no copy of their text (§3:1). ``observer_commit`` is retired (ADR-0346
§10:1): a hub whose override directory still holds a file for it refuses to start
(ADR-0334 §5:1), so the deploy that retires it removes that file.

The scout declares one flag and no value: :data:`PERSON_FLAG`, true exactly where the
observer holds a person-model store and the leaving episode is a person's, so its call is
given that person's five fields and may answer what ADR-0338 §9 lets it (§9:1-§9:3).
Framing and placement declare no flag and no value (ADR-0346 §10:1): framing's call is
given the person's fields where it has them, under ``person``, and its style and pin
judgements are read only where it was (ADR-0338 §9:4-§9:5); placement is given no person.
The user message each call sends is one JSON object the stage renders, and every value in
it is quoted source data under ADR-0098 §2; that stays in code, whatever a template says
(§1:3).

What an instruction says is guidance to a model. What must hold whatever a model
answers is held by code instead: origins, ``when``, source details and who added a
support, and every holder (ADR-0329 §9:5, ADR-0345 §2:2); that every part a memory rests on
is one its finding rests on, and a finding one of the leaving episode's (ADR-0346 §3:1);
that every candidate is accounted for (§4:6); that a name is one a part gives (§5:5);
what a round's message may back (§7:6-§7:9); and that a placement names each retrieved
memory once, by a relation of the closed set (§6:2). The instructions say those rules
too, so a model's answer usually passes the checks, but no check trusts them, and no
template changes them (ADR-0334 §7:2).
"""

from __future__ import annotations

from typing import Final

from ai_assistant.core.prompts import PromptDeclaration

__all__ = [
    "OBSERVER_FRAMING_PROMPT",
    "OBSERVER_PLACEMENT_PROMPT",
    "OBSERVER_SCOUT_PROMPT",
    "PERSON_FLAG",
]

#: Where every default ships: beside this module (ADR-0334 §3:1).
_PACKAGE: Final = "ai_assistant.orchestration.observer"

#: The scout's one flag (ADR-0334 §4:2): the call is given the leaving episode's person's
#: five fields (ADR-0338 §7:4, §9:1), and may answer what §9:2-§9:3 let it.
PERSON_FLAG: Final = "person"

#: The scout's prompt (ADR-0346 §4): one call per due episode, proposing findings.
#:
#: **What the instruction must say**, which binds the default and every override alike
#: (ADR-0334 §7:1), and which a promotion's review reads it against (§7:3): that it reads
#: one exchange, as the assistant lived it, with what its record points at (ADR-0346
#: §2); that each finding states one thing worth keeping, names the parts it rests on, at
#: least one of the exchange's own, and gives whom it is about and involves, why it
#: matters, the situations in which it matters and any narrowing with why (§4:2); that
#: parts calling for different handling are separate findings (§4:3); that every
#: candidate is named by a finding or declined with a reason (§4:6); and that a request to
#: remember or a correction is proposed unless the person said not to keep it (§7:3).
#: That every value of the message is quoted source data, and who said something is
#: stated by the keys around it, is ADR-0098 §2's. Under :data:`PERSON_FLAG`, also: that
#: ``person`` holds the person's own current choices, not set where null (ADR-0338 §3:1,
#: §3:9); that a finding which only restates one of them is marked as restating it and is
#: not kept as a memory (§9:3); and that a suggestion names a field, a value and the one
#: part of the exchange it rests on, and changes nothing (§9:2).
OBSERVER_SCOUT_PROMPT: Final = PromptDeclaration(
    name="observer_scout", package=_PACKAGE, flags=frozenset({PERSON_FLAG})
)

#: Framing's prompt (ADR-0346 §5): one call per finding, framing the memories it bears out.
#:
#: **What the instruction must say** (ADR-0334 §7:1): that it decides from the finding's
#: parts alone, judging evidence and not importance (ADR-0346 §5:1); one claim per memory,
#: an approved wording kept whole in exactly its words (§5:3); each memory's wording, its
#: supports with direction, backing, how sure, about-when and note, its ``subjects`` and
#: ``involved``, never left out, its labels, its marks and a validity end where a support
#: names one (§5:2, §9:1); a name only as a part gives it (§5:5); a relationship to the
#: user as a memory of its own (§5:6); nothing kept, with a reason, where the parts do not
#: bear the claim out (§5:6); occasions marked ``occasion`` (§7:1); what the assistant
#: said kept only as a record of the saying, or where a person took it on (§7:6-§7:9);
#: and, where ``person`` is given, the style and pin judgements (ADR-0338 §9:4-§9:5).
OBSERVER_FRAMING_PROMPT: Final = PromptDeclaration(name="observer_framing", package=_PACKAGE)

#: Placement's prompt (ADR-0346 §6:2): one call per framed memory, naming its relation to
#: each stored memory retrieved for it.
#:
#: **What the instruction must say** (ADR-0334 §7:1): that it names one relation of
#: ADR-0345 §4's closed set for each stored memory shown, with a note on how the two
#: relate for every relation but ``independent`` (ADR-0346 §6:2); ``unclear``, with what
#: it would have needed, where it cannot tell (§6:3); at most one open question the new
#: memory answers (§6:2); and that it states relations only and changes nothing of the
#: memory (§6:4).
OBSERVER_PLACEMENT_PROMPT: Final = PromptDeclaration(name="observer_placement", package=_PACKAGE)
