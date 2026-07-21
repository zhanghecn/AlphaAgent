"""Historical v5 explicit-no-action transaction trigger evaluation."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping

from alphaagent.server.services.limit_up import preboard_transaction_trigger_study as v4


STUDY_VERSION = "limit-up-preboard-transaction-disposition-v5"
DEFAULT_SESSION_COUNT = 89


def evaluate_preboard_transaction_disposition(
    *,
    session_count: int = DEFAULT_SESSION_COUNT,
) -> dict[str, object]:
    """Run v5 while preserving every frozen v4 model and account setting."""

    return v4._evaluate_preboard_transaction_trigger(
        session_count=session_count,
        study_version=STUDY_VERSION,
        coverage_contract=v4.EXPLICIT_NO_ACTION_V5_COVERAGE,
        candidate_key="v5",
    )


def render_preboard_transaction_disposition_markdown(
    report: Mapping[str, object],
) -> str:
    return v4.render_transaction_trigger_markdown(report)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate explicit-no-action transaction trigger v5"
    )
    parser.add_argument("--sessions", type=int, default=DEFAULT_SESSION_COUNT)
    parser.add_argument(
        "--format",
        choices=("json", "markdown", "both"),
        default="markdown",
    )
    parser.add_argument("--output")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report = evaluate_preboard_transaction_disposition(session_count=args.sessions)
    markdown = render_preboard_transaction_disposition_markdown(report)
    json_text = json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
    if args.format == "both":
        if not args.output:
            raise ValueError("--output is required when --format=both")
        v4._write_output(f"{args.output}.md", markdown)
        v4._write_output(f"{args.output}.json", json_text)
        return
    content = json_text if args.format == "json" else markdown
    if args.output:
        v4._write_output(args.output, content)
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
