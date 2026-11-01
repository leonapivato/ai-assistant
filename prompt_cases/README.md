# Prompt cases

The synthetic half of the prompt regression suite ([ADR-0337](../docs/adr/0337-a-prompt-change-is-judged-on-a-regression-suite-with-repeated-samples-each-recorded-call-is-asked-what-it-had-to-guess-and-a-candidate-is-promoted-after-three-clean-days.md) §3).
A case is one model call and a property its reply must have. `scripts/prompt_replay.py suite`
sends the cases; a test in the gate reads every one and checks its form, and sends nothing
(§3:6).

**Every case here is invented** (§3:2, §2:2): its people, places, messages and data are
modelled on no real person, and no text in it comes from a diagnostic entry, a copy, a case
store or any store of a hub. The review of the pull request that adds a case reads for this.

## Where a case lives

One TOML file per case, in the directory named for its prompt (§3:1):
`prompt_cases/<prompt>/<case>.toml`. The case is named `<prompt>/<case>` in a run and in its
results. Its input may instead be a JSON file beside it, which the case names (§3:4).

## What a case holds (§3:3)

```toml
prompt = "planning"            # the directory's prompt
guards = "yes_without_question" # the failure class it guards
came_from = "#3104"            # the issue, or the date, 2026-10-21, it came from
set = "development"            # or "held_out": never shown to whoever drafts a candidate
samples = 3                    # how often it is sent under each version (§5:2)

[flags]                        # exactly the flags the prompt declares, each true or false;
                               # left out where it declares none, as planning does
[property]                     # a code check and its parameters, or "read"
check = "none_of"
capabilities = ["email", "run_approved"]

[input]                        # the call's request after the system message (§3:4)
file = "<case>.json"           # or, for a completion: messages = [{ role = "user", ... }]
```

A planning case's input is a round's exchange after its instruction, as its given entry
records it, and its offered tools (ADR-0356 §11:4), best held in a JSON file beside it:

```json
{
  "exchange": {"briefing": "# The stimulus\n...", "steps": [{"response": {}, "report": {}}]},
  "tools": [{"name": "text", "description": "...", "parameters": {}}]
}
```

`briefing` is the work's first user turn, the tagged text the stage renders (ADR-0356 §3).
`steps`, left out for a work's first round, are its earlier rounds, each its response and
the report on it, as `PlanningExchange` holds them, each response with no continuation
(§6:3). The run renders the instruction from the version it sends, and sends the exchange
whole. A completion's input is `messages`, its request after the system message.

A case of the prompt `follow_up` (§3:5) asks the follow-up question about a call that has
completed, so its input is that call whole, and its instruction is rendered as the request's
last user message, as the hub sends it (§6:3). It declares no `[flags]`, since `follow_up`
declares none, and its property is `read`. Its input, best held in a JSON file beside it:

```json
{
  "followed": {"prompt": "understanding"},
  "messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}],
  "response": "<the followed call's reply as text>"
}
```

`followed` names the followed call's prompt and, only as a record of where the case came
from, its flags where its prompt declares any (understanding declares none). `messages` is
its request whole, with its one system message. For a planning round, `tools` holds the
tools it offered, and `response` its whole response as
pydantic-ai serialises it, the form planning's returned entry keeps it in: the run sends it
back whole, and closes each call it proposed with a result saying it was not run (§6:4).
An invented round's response cannot carry thinking a provider accepts, since a provider
refuses a signature it did not issue, so the seed case follows a completion.

A `read` property names, in `read`, what a person reading the reply looks for:

```toml
[property]
check = "read"
read = "Greets the user back and recites nothing of what the person block holds."
```

The closed sets are the runner's, in `scripts/prompt_replay.py`, and a case names nothing
outside them:

- **failure classes**, `FAILURE_CLASSES`, each saying whether its property is safety-relevant
  (§5:1). A case guarding a safety-relevant one declares at least three samples (§5:2). A
  class found later is added there.
- **code checks**, `CODE_CHECKS`, each with what it decides, the prompts it reads a reply of
  and the parameters it takes. Prefer a code check wherever code can decide; everything else
  is `read` (§3:5).

A code check reads a reply as the prompt's own stage reads it, so a reply the hub would
refuse passes no check. A case asserts what a reply does, never what an instruction says.

A case's input is best the request the package's own stage renders, from invented records,
kept beside the case as the JSON a given entry records: a hand-written request can miss a
field the stage shows, and a case that does not show it guards nothing about it. A rendered
request goes stale when the code changes how it renders data; a stale case is rewritten, not
trusted.

## Running them

```bash
uv run python scripts/prompt_replay.py suite --model <provider:model> --count
uv run python scripts/prompt_replay.py suite --model <provider:model> \
    --candidate <draft>/planning.txt --results <results-dir>
```

`--follow-up` asks the follow-up after every sample's response, of every case but a
`follow_up` case, with the package's default or `--follow-up <draft>/follow_up.txt`, and
writes its answer into that sample's line (§7:1); each follow-up counts against the bound.

The run prints, for each case and version, how many samples passed the case's code check of
how many were sent, or that the case is to be read, and writes each reply to
`<results-dir>/suite-<run>.jsonl`. A candidate is green for its prompt where, on every case,
it passes at least as many samples as the default, and every sample of each case it was
written to fix (§9:2); a `read` case's samples pass where the person who reads them says so.
