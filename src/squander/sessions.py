"""Phase 1: aggregate parsed usage records into per-session totals and cost."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from .parser import UsageRecord
from .pricing import PriceBook


@dataclass
class SessionSummary:
    session_id: str
    project: str
    models: List[str]
    first_timestamp: datetime
    last_timestamp: datetime
    api_calls: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    reasoning_tokens: int
    # Cost is None when any of the session's models is missing from
    # prices.yaml -- unknown, as opposed to zero.
    cost_usd: Optional[float]
    unpriced_models: List[str] = field(default_factory=list)
    records: List[UsageRecord] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
            + self.reasoning_tokens
        )


def summarize_session(
    records: List[UsageRecord],
    prices: PriceBook,
    project: str = "",
) -> Optional[SessionSummary]:
    """Roll one session's records up into totals and dollar cost.

    Sidechain (subagent) records are included in the totals: they are
    real billed API calls, and ccusage counts them too, which keeps our
    numbers comparable with the Phase 1 correctness oracle.
    """
    if not records:
        return None

    records = sorted(records, key=lambda r: r.timestamp)

    models = []
    unpriced = []
    cost = 0.0
    cost_known = True
    for r in records:
        if r.model not in models:
            models.append(r.model)
        # Cache writes bill by TTL. Use the logged 5m/1h breakdown when
        # present; when it's absent, attribute the whole write to the
        # 5m rate (the cheaper one -- a conservative lower bound).
        if r.cache_write_5m_tokens is not None or r.cache_write_1h_tokens is not None:
            write_5m = r.cache_write_5m_tokens or 0
            write_1h = r.cache_write_1h_tokens or 0
        else:
            write_5m = r.cache_write_tokens
            write_1h = 0
        call_cost = prices.cost(
            r.model,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
            cache_read_tokens=r.cache_read_tokens,
            cache_write_5m_tokens=write_5m,
            cache_write_1h_tokens=write_1h,
        )
        if call_cost is None:
            cost_known = False
            if r.model not in unpriced:
                unpriced.append(r.model)
        else:
            cost += call_cost

    return SessionSummary(
        session_id=records[0].session_id,
        project=project,
        models=models,
        first_timestamp=records[0].timestamp,
        last_timestamp=records[-1].timestamp,
        api_calls=len(records),
        input_tokens=sum(r.input_tokens for r in records),
        output_tokens=sum(r.output_tokens for r in records),
        cache_read_tokens=sum(r.cache_read_tokens for r in records),
        cache_write_tokens=sum(r.cache_write_tokens for r in records),
        reasoning_tokens=sum(r.reasoning_tokens or 0 for r in records),
        cost_usd=cost if cost_known else None,
        unpriced_models=unpriced,
        records=records,
    )
