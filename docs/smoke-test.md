# Smoke test — codex-review CI (throwaway)

This file exists only to exercise the `codex-review` workflow (ADR-0012)
end to end after the `OPENAI_API_KEY` secret was provisioned. It is **not**
meant to be merged — close the PR and delete the branch once the review has
posted.

A couple of deliberately reviewable lines so the reviewer has something to chew
on:

- The `assemble()` result is validated with `CurrentContext.model_validate(...)`.
- Retryable model failures back off with full jitter (ADR-0011).

If a Codex review comment appears on the PR naming this commit's SHA, the
pipeline works.
