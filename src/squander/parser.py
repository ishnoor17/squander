"""Phase 0: parse Claude Code JSONL session logs into structured records.

Claude Code writes one JSONL line per *content block* of an assistant
message (thinking / text / tool_use), not one line per API call. All
lines belonging to the same API call share the same message id and
carry an identical, already-cumulative ``usage`` block -- so naively
summing every line over-counts tokens by however many content blocks
the message had. Records here are deduplicated by message id to
recover exactly one entry per actual API call.

Note on reasoning tokens: Claude's own extended-thinking tokens are
billed as part of ``output_tokens`` and are not broken out separately
in Claude Code's logs, so ``reasoning_tokens`` is ``None`` for Claude
records today. The field is kept in the data model (per the project
brief) so a provider that does report it separately doesn't require a
schema change later.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional, Union


@dataclass(frozen=True)
class UsageRecord:
    """Token usage for a single Claude API call (one assistant message)."""

    session_id: str
    message_id: str
    request_id: Optional[str]
    timestamp: datetime
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    # Breakdown of cache_write_tokens by cache TTL, when the log provides
    # it. 1-hour-TTL writes bill at a higher rate than 5-minute ones, so
    # the split matters for accurate pricing later.
    cache_write_5m_tokens: Optional[int]
    cache_write_1h_tokens: Optional[int]
    reasoning_tokens: Optional[int]
    is_sidechain: bool

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
            + (self.reasoning_tokens or 0)
        )


def _parse_timestamp(raw: str) -> datetime:
    # Claude Code timestamps are ISO 8601 UTC, e.g. "2026-07-16T14:45:22.100Z".
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _record_from_entry(entry: dict, fallback_session_id: str) -> Optional[UsageRecord]:
    if entry.get("type") != "assistant":
        return None

    message = entry.get("message")
    if not isinstance(message, dict):
        return None

    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None

    message_id = message.get("id")
    timestamp_raw = entry.get("timestamp")
    if not message_id or not timestamp_raw:
        return None

    cache_creation = usage.get("cache_creation")
    if isinstance(cache_creation, dict):
        cache_write_5m = cache_creation.get("ephemeral_5m_input_tokens")
        cache_write_1h = cache_creation.get("ephemeral_1h_input_tokens")
    else:
        cache_write_5m = None
        cache_write_1h = None

    return UsageRecord(
        session_id=entry.get("sessionId", fallback_session_id),
        message_id=message_id,
        request_id=entry.get("requestId"),
        timestamp=_parse_timestamp(timestamp_raw),
        model=message.get("model", "unknown"),
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        cache_read_tokens=usage.get("cache_read_input_tokens", 0),
        cache_write_tokens=usage.get("cache_creation_input_tokens", 0),
        cache_write_5m_tokens=cache_write_5m,
        cache_write_1h_tokens=cache_write_1h,
        reasoning_tokens=usage.get("reasoning_tokens"),
        is_sidechain=bool(entry.get("isSidechain", False)),
    )


def parse_session_file(path: Union[Path, str]) -> list:
    """Parse one Claude Code session JSONL file into deduplicated usage records.

    Each API call is logged as multiple JSONL lines (one per content
    block), all sharing the same message id and an identical usage
    total. Only the first line seen for a given message id is kept.
    Non-assistant lines, and assistant lines without a usage block
    (e.g. still streaming when the log was read), are skipped.
    Malformed lines are skipped rather than raising, since session
    logs are append-only and can contain a partially written final
    line.
    """
    path = Path(path)
    fallback_session_id = path.stem

    seen_message_ids = set()
    records = []

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            record = _record_from_entry(entry, fallback_session_id)
            if record is None:
                continue
            if record.message_id in seen_message_ids:
                continue

            seen_message_ids.add(record.message_id)
            records.append(record)

    return records


def default_session_log_dir() -> Path:
    """Directory Claude Code writes session logs under (``~/.claude/projects``)."""
    return Path.home() / ".claude" / "projects"


def iter_session_files(root: Optional[Union[Path, str]] = None) -> Iterator[Path]:
    """Yield every session JSONL file under the Claude Code log directory."""
    root = Path(root) if root is not None else default_session_log_dir()
    if not root.exists():
        return
    yield from sorted(root.glob("*/*.jsonl"))
