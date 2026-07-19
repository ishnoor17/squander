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
- [x] **Phase 1 — Reproduce.** Aggregate into per-session totals and
      dollar cost; validated against `npx ccusage session` — token
      counts and costs match to the microdollar on every session.
- [x] **Phase 2 — Diagnose.** One waste detector: repeated large-context
      re-sends across consecutive turns (the review-loop pattern).

## The detector

`squander analyze` flags **review-loop waste**: runs of consecutive API
calls that each re-read a large, mostly-overlapping context prefix.
Every call after the run's first re-bills that context (as cache-read
tokens); a fresh session or trimmed context would have avoided most of
it. The rule is deliberately narrow — one unambiguous signal, not a
vague efficiency score: at least 3 consecutive main-chain calls, each
re-reading ≥20K cached tokens covering ≥80% of the previous call's
context.

```
Waste findings
--------------
Session d39cafe7  *  $16.0853  *  mixed models
  !  Review loop detected: ~198.0K tokens of context re-sent 39x in a row
     Re-billed cost ~ $7.4345 (46% of this session)
     A fresh session or trimmed context would have cut most of it.
```

The re-billed cost is computed from exact logged token counts at each
call's own model rate; the `~` marks that "how much a trimmed context
would have saved" is inherently an approximation.

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
Prices are USD per 1,000,000 tokens.

Two pricing details that matter for accuracy (both validated against
ccusage's output):

- **Cache writes bill by TTL** — 1.25× the input price for the
  5-minute cache, 2× for the 1-hour cache. Claude Code uses the
  1-hour cache, and the session logs break writes down by TTL, so
  squander prices each bucket at its real rate.
- **`claude-sonnet-5` ships at its introductory pricing** ($2/$10 per
  1M), which applies through 2026-08-31 — update `prices.yaml` to the
  standard rates after that date.

## Usage

```bash
squander analyze                 # all sessions under ~/.claude/projects
squander analyze --logs-dir DIR  # a different log directory
squander analyze --prices FILE   # a different prices.yaml
```

To validate against ccusage yourself: run `npx ccusage session` and
compare its per-session token totals and costs with
`squander analyze` — they should match exactly.

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
