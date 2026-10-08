---
name: delegate-to-haiku
description: Decide whether a subtask is safe to hand to a Haiku 5.5 subagent, and how to brief it so the result can be trusted. Use when about to spawn an Agent for well-scoped, low-judgment work (file sweeps, mechanical edits, log triage, summarizing known content, boilerplate) and you want it done cheaply and fast. Do not use for design decisions, debugging with unknown root cause, security-sensitive code, or anything you'd have to fully redo to verify.
---

# Delegating to Haiku 5.5

Haiku 5.5 (`model: "haiku"` on the Agent tool) is fast and cheap, and reliable
when the task is **bounded, concrete, and checkable**. It is weaker at holding
long chains of reasoning, weighing trade-offs, and noticing that the brief
itself is wrong. Delegate the *doing*, keep the *deciding*.

## The comfort test

Delegate only if **every** answer is "yes":

1. **Can I state the task in a few sentences with a concrete finish line?**
   ("List every call site of `chunk_limit` under `app/backend`", not
   "figure out why latency regressed").
2. **Is the answer mostly lookup or mechanics, not judgment?** No choosing
   between designs, no inferring intent, no "decide what's best".
3. **Can I verify the result cheaply?** A grep, a test run, a diff skim, or a
   spot-check of 2–3 items. If checking costs as much as doing, do it yourself.
4. **Is a wrong answer low-cost and recoverable?** Nothing pushed, published,
   deleted, sent, or merged on Haiku's word alone.
5. **Does it need little of the context I already hold?** If the brief would
   need half this conversation, the hand-off costs more than it saves.

Any "no" → do it inline, or use a stronger model.

## Good fits

- Broad read-only sweeps: find files/symbols/patterns, inventory configs,
  list TODOs, map which scripts call which.
- Mechanical, rule-based edits across many files where the rule is exact
  (rename X→Y, add a header, update an import path) — followed by your diff review.
- Summarizing or extracting from content you point it at: a long log, a CI
  job output, a doc, a JSON blob → "return the failing test names and first
  error line".
- Boilerplate from a precise spec or an existing example to copy
  (a new test case shaped like `test_foo`, a fixture, a docstring pass).
- Format conversions: CSV↔JSON, table reshaping, regenerating a list in a
  given layout.
- Parallel fan-out of many small independent lookups.

## Keep for yourself (or a stronger model)

- Root-causing bugs, flaky tests, performance or latency regressions.
- Architecture, API, or schema decisions; reviewing a design.
- Security-, auth-, or data-loss-sensitive changes.
- Concurrency, audio/ML pipeline timing, or numerics where subtle errors
  look correct.
- Anything that ends in an outward action: commits, pushes, PRs, comments,
  messages, deletes.
- Tasks where the instructions are ambiguous and the subagent would have to
  guess.

## How to brief Haiku

Haiku starts cold. Write the prompt so it cannot misread the job:

- **Goal in one line**, then the exact scope (directories, file globs, symbols).
- **Explicit steps** if order matters; explicit rules for edits ("change only
  the import line; do not reformat").
- **What not to do**: no commits, no pushes, no edits outside scope, no
  "improvements" beyond the ask.
- **Output shape**: e.g. "Return a markdown list of `path:line — snippet`",
  or "Return only the diff summary and any files you skipped and why".
- **Ask it to flag uncertainty** instead of guessing: "If something doesn't fit
  the rule, list it under UNSURE and leave it unchanged."

Template:

```
Agent({
  description: "<3-5 words>",
  model: "haiku",
  prompt: `Goal: <one sentence>.
Scope: <paths/globs>. Do not touch anything else.
Steps:
1. ...
2. ...
Rules: <exact rule>. Do not commit, push, or reformat unrelated code.
Output: <exact format>. List anything ambiguous under UNSURE instead of guessing.`
})
```

Use `subagent_type: "Explore"` for read-only searches; the general-purpose
agent when edits are needed. Run independent Haiku tasks in parallel in one
message.

## After it returns

- The report is not shown to the user — relay what matters.
- **Verify before trusting**: spot-check claims (open 2–3 cited lines), run the
  repo's checks after edits (e.g. `script/validate.sh` here), and read the diff.
- If it reported UNSURE items or the result looks thin or off, finish those
  yourself rather than re-delegating the same brief.
- Never repeat Haiku's conclusions to the user as verified facts until you
  have checked them.
