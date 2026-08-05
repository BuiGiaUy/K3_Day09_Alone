"""Command-line entry point for the dispute resolution pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .agents import AgentError
from .coordinator import CoordinatorAgent, publish_run
from .repository import DataError, OlistRepository, load_cases


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Process Olist disputes using deterministic autonomous agents."
    )
    result.add_argument("--input-dir", type=Path, default=Path("input"))
    result.add_argument("--data-dir", type=Path, default=Path("data"))
    result.add_argument("--output-dir", type=Path, default=Path("output"))
    result.add_argument("--logging-dir", type=Path, default=Path("logging"))
    result.add_argument(
        "--validate-only",
        action="store_true",
        help="compute and validate all cases without writing artifacts",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        cases = load_cases(args.input_dir)
        if len(cases) != 50:
            raise DataError(f"expected exactly 50 cases, found {len(cases)}")
        repository = OlistRepository(
            args.data_dir, (case.claimed_order_id for case in cases)
        )
        coordinator = CoordinatorAgent(repository)
        outputs = {case.case_id: coordinator.process(case) for case in cases}
        if set(outputs) != {case.case_id for case in cases}:
            raise AgentError("output case set does not match input case set")
        if not args.validate_only:
            publish_run(outputs, coordinator.events, args.output_dir, args.logging_dir)
        summary = Counter(
            output["assessment"]["primary_issue"] for output in outputs.values()
        )
        print(
            json.dumps(
                {
                    "validated_cases": len(outputs),
                    "written": not args.validate_only,
                    "issue_counts": dict(sorted(summary.items())),
                    "trace_events": len(coordinator.events),
                },
                indent=2,
            )
        )
        return 0
    except (DataError, AgentError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
