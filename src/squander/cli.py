"""Command-line entry point: ``squander analyze``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from .detectors import detect_context_resend
from .parser import default_session_log_dir, iter_session_files, parse_session_file
from .pricing import load_prices
from .sessions import SessionSummary, summarize_session


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _fmt_cost(summary: SessionSummary) -> str:
    if summary.cost_usd is None:
        return "?"
    return f"${summary.cost_usd:.4f}"


def _project_label(log_file: Path) -> str:
    # Log directories are the session's cwd with '/' munged to '-',
    # e.g. '-Users-me-myproject'. The last segment is the readable bit.
    return log_file.parent.name.rsplit("-", 1)[-1]


def _analyze(args: argparse.Namespace) -> int:
    logs_dir = Path(args.logs_dir) if args.logs_dir else default_session_log_dir()
    if not logs_dir.exists():
        print(f"error: session log directory not found: {logs_dir}", file=sys.stderr)
        return 1

    prices = load_prices(args.prices)

    summaries: List[SessionSummary] = []
    for log_file in iter_session_files(logs_dir):
        records = parse_session_file(log_file)
        summary = summarize_session(records, prices, project=_project_label(log_file))
        if summary is not None:
            summaries.append(summary)

    if not summaries:
        print(f"No sessions with API usage found under {logs_dir}")
        return 0

    summaries.sort(key=lambda s: s.first_timestamp)

    header = (
        f"{'Session':<10} {'Project':<14} {'Model':<18} {'Calls':>5} "
        f"{'Input':>8} {'Output':>8} {'Cache R':>9} {'Cache W':>9} {'Cost':>10}"
    )
    print(header)
    print("-" * len(header))
    total_cost = 0.0
    any_unpriced = False
    for s in summaries:
        model_label = s.models[0] if len(s.models) == 1 else f"{s.models[0]} +{len(s.models) - 1}"
        print(
            f"{s.session_id[:8]:<10} {s.project[:14]:<14} {model_label:<18} {s.api_calls:>5} "
            f"{_fmt_tokens(s.input_tokens):>8} {_fmt_tokens(s.output_tokens):>8} "
            f"{_fmt_tokens(s.cache_read_tokens):>9} {_fmt_tokens(s.cache_write_tokens):>9} "
            f"{_fmt_cost(s):>10}"
        )
        if s.cost_usd is not None:
            total_cost += s.cost_usd
        else:
            any_unpriced = True

    print("-" * len(header))
    total_label = f"${total_cost:.4f}" + ("+" if any_unpriced else "")
    print(f"{'Total':<10} {'':<14} {'':<18} {sum(s.api_calls for s in summaries):>5} "
          f"{_fmt_tokens(sum(s.input_tokens for s in summaries)):>8} "
          f"{_fmt_tokens(sum(s.output_tokens for s in summaries)):>8} "
          f"{_fmt_tokens(sum(s.cache_read_tokens for s in summaries)):>9} "
          f"{_fmt_tokens(sum(s.cache_write_tokens for s in summaries)):>9} "
          f"{total_label:>10}")

    all_findings = [
        (s, f) for s in summaries for f in detect_context_resend(s.records, prices)
    ]
    if all_findings:
        print("\nWaste findings")
        print("--------------")
        last_session = None
        for s, f in all_findings:
            if s.session_id != last_session:
                model_label = s.models[0] if len(s.models) == 1 else "mixed models"
                print(
                    f"Session {s.session_id[:8]}  *  {_fmt_cost(s)}  *  {model_label}"
                )
                last_session = s.session_id
            print(
                f"  !  Review loop detected: ~{_fmt_tokens(f.avg_context_tokens)} tokens "
                f"of context re-sent {f.calls}x in a row"
            )
            if f.redundant_cost_usd is not None:
                if s.cost_usd:
                    share = f" ({f.redundant_cost_usd / s.cost_usd:.0%} of this session)"
                else:
                    share = ""
                print(
                    f"     Re-billed cost ~ ${f.redundant_cost_usd:.4f}{share}"
                )
            else:
                print(
                    f"     Re-billed tokens: {_fmt_tokens(f.redundant_tokens)} "
                    f"(cost unknown -- model not in prices.yaml)"
                )
            print(
                "     A fresh session or trimmed context would have cut most of it."
            )

    unpriced = sorted({m for s in summaries for m in s.unpriced_models})
    if unpriced:
        print(
            f"\nwarning: no prices configured for: {', '.join(unpriced)} -- "
            f"their sessions show cost '?' and the total is a lower bound. "
            f"Add them to prices.yaml."
        )
    print("\nAll token counts are exact (read from provider usage data).")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="squander",
        description="Diagnose wasted tokens in Claude Code sessions.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser(
        "analyze", help="Per-session token totals and cost."
    )
    analyze.add_argument(
        "--logs-dir",
        help="Claude Code session log directory (default: ~/.claude/projects).",
    )
    analyze.add_argument(
        "--prices",
        help="Path to prices.yaml (default: ./prices.yaml, then the repo copy).",
    )
    analyze.set_defaults(func=_analyze)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
