# squander

Every existing tool tells you *how much* you spent on agentic coding.
Squander tells you *where you wasted it* — and why.

Tools like [`ccusage`](https://github.com/ryoppippi/ccusage) and Claude
Code's own `/usage` already solve token *tracking*: they read your local
session logs and break spend down by session, day, skill, or subagent.
Squander doesn't compete with that layer. It reads the same local data
and adds the layer nobody's built yet: a **diagnostic** pass that maps
tokens to *where in the workflow* they went, and flags waste.

The motivating evidence (Salim et al., "Tokenomics"): in a typical
agentic run, the iterative review/refinement loop eats ~59% of tokens,
and input tokens dominate (~54%) because a growing context gets
re-billed on every turn. That re-billing is invisible if you only look
at "how much." Squander makes it visible.

## Status

Built in phases; each phase is a correctness checkpoint before the next
is trusted.

- [x] **Phase 0 — Parse.** Read Claude Code's local JSONL session logs
      into structured per-API-call records (timestamp, model, input /
      output / cache-read / cache-write / reasoning tokens).
- [ ] **Phase 1 — Reproduce.** Aggregate into per-session totals and
      dollar cost; validate against `npx ccusage session`.
- [ ] **Phase 2 — Diagnose.** One waste detector: repeated large-context
      re-sends across consecutive turns (the review-loop pattern).

## Data source

Claude Code writes session logs as JSONL under `~/.claude/projects/<project>/<session-id>.jsonl`,
one file per session. `squander` reads these directly — no network
calls, nothing leaves your machine.

One quirk worth knowing: Claude Code writes **one JSONL line per
content block** of an assistant message (thinking / text / tool_use),
not one line per API call, and every line for a given message repeats
the *same cumulative* `usage` totals. Summing every line would
over-count tokens by however many content blocks the message had.
`squander`'s parser deduplicates by message id to recover exactly one
record per real API call.

## Pricing

Model prices live in [`prices.yaml`](prices.yaml), never in code —
providers change them, and a config file means no redeploy to update.
Prices are USD per 1,000,000 tokens. **Verify the shipped values
against current provider pricing before trusting them** — they're
placeholders to be confirmed, not gospel.

## Estimates vs. exact counts

Anywhere a figure is derived rather than read directly from a model's
reported usage (e.g. a character-based token estimate), it is labeled
as an estimate. Everything else is an exact count from the provider's
own `usage` block.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```
