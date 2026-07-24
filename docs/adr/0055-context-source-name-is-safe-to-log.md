# 55. A `ContextSource.name` is contractually safe to log

- Status: Accepted
- Date: 2026-07-24
- Decides issue #233, a Codex adversarial finding raised at `blocker` against
  PR #230 and waived there. The finding's grounding was wrong on two counts
  (below), but the question under it — whether `name` is *contractually* safe to
  log or merely happens to be — was left open, and it should be settled across
  every diagnostic at once rather than one call site at a time.
- **Not a `core` contract change.** The `ContextSource` seam lives inside
  `context/`, not in `core/protocols.py` (ADR-0008 §2 keeps it there so the only
  data crossing a subsystem boundary is the typed `CurrentContext`). So golden
  rule 5's separate-PR requirement does not apply and this ADR merges with the
  one-line docstring change it authorises. No Protocol moves, no `core` type or
  `Settings` field is touched.
- **No ratified text is rewritten.** This strengthens ADR-0008 §2's seam the way
  ADR-0033 strengthened ADR-0026 §4's join — by stating an obligation the seam
  already implied, not by editing the earlier decision. ADR-0008 §2's `Status`
  stays as it is; ADR-0001's procedure for changing a past decision is not
  triggered.
- Refs: ADR-0004 §1, ADR-0004 §5, ADR-0008 §2.

## Context

`AssemblingContextProvider` logs `source=_safe_name(source)` at three call
sites: two `warning`s when an optional source degrades or times out
(`_safe_contribute`), and one when a straggler is abandoned (`_abandon`). Every
one puts a source's own `name` into a log line.

ADR-0004 §5 keeps Tier 0/1 data out of logs, and the module already works hard
to honour it elsewhere: the degradation log records `type(exc).__name__`, never
`str(exc)`, precisely because a source wraps calendars, tasks and email and its
*exception message* can quote the Tier 1 content it was fetching. That care
around the message throws the treatment of `name` into relief — `name` is logged
verbatim. The finding asked whether that is safe.

Two of the finding's premises were false, which is why it was waived rather than
acted on in #230:

1. It called the exposure new to that diff. It is not: the two older `warning`
   sites already logged `source=_safe_name(source)` on `main`. Fixing only the
   new site would leave the module inconsistent with itself.
2. It said `ContextSource.name` "only promises a stable identifier, not a
   privacy-safe one". The docstring said the opposite — *"a stable identifier,
   used for collision reporting and logging"* — so logging is the documented
   use and a source putting personal data there was already misusing the seam.

But "the docstring names logging as the use" is not quite the same as "the
docstring obliges the source to keep the value loggable". The first describes
what the assembler does; the second is a duty on the source author. The gap
between them is real, and a future source author reading only the first could
reasonably mint `name = f"{user.email} calendar"` and consider themselves
conforming. That is the question worth settling.

## Decision

**We will state, on the `ContextSource.name` seam, that the value is Tier 2 /
operational and must stay so — and keep the assembler logging it verbatim.**

Concretely, `ContextSource.name`'s docstring gains the obligation: `name` is
Tier 2 (ADR-0004 §1); it must never embed Tier 0/1 data — no secret, and no
value derived from user or third-party personal data (ADR-0004 §5). A source
that wraps personal data names *itself* (`"calendar"`), never the data it holds
(`"alice@example.com calendar"`).

This is the first of the two options the issue named — state the obligation at
the seam — and not the second — have the provider log a positional or
provider-assigned identifier instead. The second was rejected:

- It changes every existing diagnostic to defend against a source that does not
  exist and would now be in breach of a written contract if it did.
- A provider-assigned index (`source[2]`) is a *worse* diagnostic than a name: a
  reader grepping logs for a flaky calendar source wants "calendar", not a
  position that shifts when the wiring is reordered. Loggability is the whole
  point of `name`; replacing it with something unloggable to make it safe to log
  would defeat the field.
- The obligation is cheap to state and impossible to satisfy accidentally: a
  source author has to choose to put personal data in an identifier, and now
  does so against an explicit prohibition rather than an ambiguous silence.

The assembler therefore keeps trusting `name`. Its existing defensiveness
(`_safe_name`, `_log_safe_name`) stays — but it guards against a `name` *access*
that raises, which is a different failure from a `name` that leaks, and this
decision does not ask it to redact a conforming value.

## Consequences

- **The seam now carries a duty, not just a use.** A source that puts personal
  data in `name` is in breach of a written contract, the same way a source that
  ignores `CancelledError` is (ADR-0033). The assembler is entitled to log the
  value on that basis, and the `type(exc).__name__` care around the *message*
  is what still guards the genuinely untrusted half of each log line.
- **No behaviour changes.** The code already logs `_safe_name(source)`; this
  makes the contract it relies on explicit. The only diff outside this ADR is
  one docstring.
- **It is stated once, for all three call sites**, which is what the issue asked
  for and what a per-site fix could not give.
- **Revisit if** a real source ever needs a user-derived identifier for its own
  reasons — at which point the assembler, not the source, would have to own a
  loggable label, and the second option above becomes the live one.
