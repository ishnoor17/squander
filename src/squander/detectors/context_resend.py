"""Phase 2: detect review-loop waste -- repeated large-context re-sends.

The pattern (Salim et al., "Tokenomics"): in an iterative review/refine
loop, the same growing context is re-sent -- and re-billed -- on every
turn. Tracking tools show the total; this detector shows how much of it
was the *same* context billed again and again.

In Claude Code's logs the pattern is visible per API call: each call's
``cache_read_input_tokens`` is the previously-sent context being read
back (and re-billed at the cache-read rate). A review loop appears as a
run of consecutive calls that each re-read a large, mostly-overlapping
prefix while adding little new. Everything after the run's first call
is redundant billing that a fresh session or trimmed context would have
avoided.

Detection rule (deliberately narrow -- one unambiguous signal):
a maximal run of >= MIN_RUN_CALLS consecutive main-chain calls where
each call (a) re-reads at least MIN_CONTEXT_TOKENS from cache, and
(b) re-reads at least OVERLAP_FRACTION of the previous call's total
context. Sidechain (subagent) calls carry their own separate context,
so they are excluded rather than allowed to break or fake a run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from ..parser import UsageRecord
from ..pricing import PriceBook

# A call must re-read at least this much cached context to count as a
# "large" re-send.
MIN_CONTEXT_TOKENS = 20_000

# A run must span at least this many consecutive calls to be reported.
MIN_RUN_CALLS = 3

# Each call must re-read at least this fraction of the previous call's
# total context for the two to count as "the same context re-sent".
OVERLAP_FRACTION = 0.8


@dataclass(frozen=True)
class ContextResendFinding:
    session_id: str
    start: datetime
    end: datetime
    calls: int
    # Mean total context (input + cache read + cache write) per call in
    # the run -- the "~38K tokens" figure.
    avg_context_tokens: int
    # Cache-read tokens billed on every call after the run's first: the
    # redundant re-billing.
    redundant_tokens: int
    # Dollar cost of the redundant tokens, at each call's own model
    # cache-read rate. None if any model in the run is unpriced.
    redundant_cost_usd: Optional[float]


def _context_tokens(r: UsageRecord) -> int:
    """Total context sent with one call: fresh input + cached prefix."""
    return r.input_tokens + r.cache_read_tokens + r.cache_write_tokens


def detect_context_resend(
    records: List[UsageRecord],
    prices: PriceBook,
    min_context_tokens: int = MIN_CONTEXT_TOKENS,
    min_run_calls: int = MIN_RUN_CALLS,
    overlap_fraction: float = OVERLAP_FRACTION,
) -> List[ContextResendFinding]:
    """Find runs of repeated large-context re-sends in one session."""
    main_chain = sorted(
        (r for r in records if not r.is_sidechain),
        key=lambda r: r.timestamp,
    )

    findings = []
    run: List[UsageRecord] = []

    def continues_run(prev: UsageRecord, curr: UsageRecord) -> bool:
        if curr.cache_read_tokens < min_context_tokens:
            return False
        return curr.cache_read_tokens >= overlap_fraction * _context_tokens(prev)

    def flush_run() -> None:
        if len(run) < min_run_calls:
            return
        redundant = run[1:]
        cost_known = True
        cost = 0.0
        for r in redundant:
            call_cost = prices.cost(r.model, cache_read_tokens=r.cache_read_tokens)
            if call_cost is None:
                cost_known = False
                break
            cost += call_cost
        findings.append(
            ContextResendFinding(
                session_id=run[0].session_id,
                start=run[0].timestamp,
                end=run[-1].timestamp,
                calls=len(run),
                avg_context_tokens=sum(_context_tokens(r) for r in run) // len(run),
                redundant_tokens=sum(r.cache_read_tokens for r in redundant),
                redundant_cost_usd=cost if cost_known else None,
            )
        )

    for r in main_chain:
        if run and continues_run(run[-1], r):
            run.append(r)
            continue
        flush_run()
        # A run can only start on a call that itself sends large context.
        run = [r] if _context_tokens(r) >= min_context_tokens else []
    flush_run()

    return findings
