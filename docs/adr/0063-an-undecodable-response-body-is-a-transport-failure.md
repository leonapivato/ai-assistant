# 63. An undecodable response body is a transport failure, not a permanent one

- Status: Accepted
- Date: 2026-07-24

## Context

`_classify` in `models/provider.py` maps a failed completion onto the
`retryable`/`routable` taxonomy (ADR-0011, ADR-0013). It dispatches on
pydantic-ai's exception hierarchy — `ModelHTTPError` for a status, `ModelAPIError`
for a connection-level fault — and anything it does not recognise becomes a bare
`ModelError`: neither retryable nor routable. That default is deliberate and
right, for the reason ADR-0011 gave: misclassifying something as retryable is
worse than not classifying it at all.

But not every failure arrives inside that hierarchy. Building the two-vendor
offline harness (ADR-0061) surfaced a class of failure that escapes it entirely,
and `#352` reproduced it identically on both vendors: a `200` whose body is not
JSON — the classic case being a load balancer, proxy or captive portal answering
with its own HTML error page instead of forwarding to the model — makes the
vendor SDK's decode step raise a bare `json.JSONDecodeError`. Nothing wraps it,
so it reaches `_classify` as a stdlib exception and falls through to the
conservative default.

That default is wrong here in both directions at once, and this is the failure
where being wrong costs most. A gateway substituting an error page is the most
transient fault there is, and it is *someone else's* infrastructure: the next
attempt may not meet the broken hop at all, and a different provider is a
different path entirely. Today `RetryingProvider` will not retry it and
`RoutingProvider` will not fall back off it, so an intermediary hiccup is a
permanent failure of the whole request. Once `#353` gives the composed router
more than one route, this is precisely the case a fallback list is bought for —
and it would not engage.

So the narrow question is what to do with a non-JSON body. The real question is
the general one: **what should `_classify` do with any exception the vendor SDK
raises that pydantic-ai does not wrap?** Three answers were on the table, and
the evidence for choosing between them is empirical, not theoretical.

Driving `PydanticAIProvider` at unwrapped failures shows what actually lands
there. Alongside the decode failure:

- `ImportError: Please install the 'cohere' package …` — a provider extra that
  is not installed. This is ADR-0061 §1's exact scenario: a deployment sets a
  `"provider:model"` spec whose SDK was never shipped, and finds out at the
  first user request.
- `ValueError: Unknown provider: google-gla` — a model spec naming a provider
  pydantic-ai does not know. A typo in configuration.

Both reproduce identically on every attempt, from every route, forever. And the
second one matters twice over, because **`json.JSONDecodeError` is a subclass of
`ValueError`**: any rule phrased against the base class sweeps in the
configuration typo along with the gateway page.

## Decision

We will admit exceptions from outside pydantic-ai's hierarchy into the taxonomy
**by allowlist, one type at a time**, and the allowlist's admission rule is:

> An unwrapped exception is classified as transient only when its type is
> unambiguous evidence that **the response body was not the wire format** —
> i.e. the request was well-formed enough to be sent and answered, and something
> in the path substituted its own bytes for the model's answer.

Today that admits exactly one type, `json.JSONDecodeError`, classified as
`ModelUnavailableError` — **retryable and routable**, where it was previously
neither. Everything else unwrapped keeps the conservative default.

Three things about the shape of that rule are load-bearing.

**It is about where in the stack the failure happened, not about how transient
the failure sounds.** A decode failure can only occur after bytes came back, so
it says nothing about our request; it is by construction a property of the path,
which makes it both retryable (the path may be healthy next time) and routable
(another provider is another path). The `ImportError` and `ValueError` above
happen *before* anything is on the wire and travel with the request, so no
amount of retrying or re-routing changes them.

**It matches `json.JSONDecodeError` and never its `ValueError` base.** The
subclass relationship is the trap the rule is written to avoid, and the boundary
is pinned by a test (`test_a_plain_value_error_stays_permanent`) rather than left
to a comment.

**It reuses `ModelUnavailableError` rather than adding or re-flagging a class.**
`ModelResponseError` is the closer-sounding name — "the provider replied, but the
response was malformed" — but its disposition is wrong (not retryable), and
flipping that flag would change the disposition of every `UnexpectedModelBehavior`
too, including structured-output mismatches that are genuinely permanent. Adding
a new class would give the same two flags a second name for no behavioural gain.
`ModelUnavailableError`'s "unreachable or failing" reads correctly here: a `200`
carrying someone else's error page is the provider's path failing, whatever
status the failing hop chose to put on it.

### The trade, stated plainly

What is now retryable that was not: **any completion whose response body fails to
JSON-decode.** In practice that is an intermediary's error page and a response
truncated mid-object; the tests pin both, because the classification must follow
from the body not decoding rather than from it starting with `<`.

The cost is real and runs the other way. A *persistently* broken path — a captive
portal, a misconfigured proxy that will answer with HTML every time for the next
hour — now burns the full retry budget (3 attempts with backoff, by default) and
then every configured fallback route before failing, where it used to fail
immediately. That is latency and quota spent to arrive at the same error.

We accept it, on the asymmetry: the failure it fixes is a total, silent loss of a
user request that a single retry would very likely have satisfied, while the
failure it costs is a slower path to an error that was going to be returned
anyway. And the cost is bounded by configuration that already exists —
`model_max_attempts` and the route list — rather than being unbounded.

What we are **not** deciding: that "unrecognised means transient". That is the
rule this ADR rejects, and the two exceptions above are why. A blanket rule would
retry a missing provider package three times with backoff and then try every
fallback, to fail identically each time.

## Consequences

**Easier.** A fallback route now engages on the failure it is most obviously for.
Once `#353` lands a fallback-model list, an intermediary breaking on one
provider's path is survivable rather than fatal — which is the property ADR-0061
put the router on the production path to obtain.

**Harder.** `_classify` now has an arm that is not anchored in pydantic-ai's
hierarchy, so it is only as correct as our knowledge of what the vendor SDKs
raise. That is why the arm is asserted at the vendor level and not only as a unit
test: `tests/models/test_provider_vendors.py` drives the real `anthropic` and
`openai` SDKs over `httpx.MockTransport` and asserts both that the disposition is
right and that the `__cause__` really is a `json.JSONDecodeError`. If either SDK
starts wrapping the body error in something pydantic-ai recognises, that test
fails rather than quietly leaving a dead arm behind.

**Still open, and deliberately out of scope.** The allowlist covers the body that
fails to *decode*, not every body a vendor cannot turn into a response. Probing
the adjacent cases shows the two vendors diverging where our classification is
weakest:

| canned response | anthropic | openai |
| --- | --- | --- |
| HTML body, `content-type: application/json` | `JSONDecodeError` → fixed here | `JSONDecodeError` → fixed here |
| HTML body, `content-type: text/html` | `AttributeError` → `ModelError` (neither) | `UnexpectedModelBehavior` → `ModelResponseError` (routable) |
| valid JSON, wrong shape | `TypeError` → `ModelError` (neither) | `UnexpectedModelBehavior` → `ModelResponseError` (routable) |

Those rows are not fixable by the rule above and must not be forced into it:
`AttributeError` and `TypeError` are what a genuine bug in our own adapter raises
too, and there is no way to tell the two apart by type. Classifying them as
transient would retry and re-route programming errors — the exact failure mode
this ADR declines. They are filed as `#362` rather than absorbed — the
`text/html` row in particular, since a real load balancer usually *does* set that
content type, so the most literal form of the failure this ADR is about is fixed
on neither vendor by this ADR alone.

**What would trigger revisiting this.** A second type asking to join the
allowlist. The admission rule above is what such a proposal has to satisfy, and
"it is usually transient" is not it — the type must be unambiguous evidence that
the body was not the wire format.
