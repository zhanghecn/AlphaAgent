"""Command-line entrypoint for the current daily low-suction research."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path


_PRICE_BASES = ("raw_unadjusted", "qfq")


def build_parser() -> argparse.ArgumentParser:
    """Build the deliberately small, read-only daily-research CLI."""

    parser = argparse.ArgumentParser(prog="low-suction-research")
    subparsers = parser.add_subparsers(dest="command", required=True)

    daily_factor_audit = subparsers.add_parser(
        "daily-factor-audit",
        help="audit qfq and security prerequisites for the daily factor study",
    )
    _add_daily_factor_range_arguments(daily_factor_audit)

    daily_factor_study = subparsers.add_parser(
        "daily-factor-study",
        help="run the frozen daily oversold/trend factor study",
    )
    _add_daily_factor_range_arguments(daily_factor_study)
    _add_price_basis_argument(daily_factor_study)

    comprehensive_study = subparsers.add_parser(
        "daily-factor-comprehensive-study",
        help="audit cases, conditions, and close-only exits for the daily factor study",
    )
    _add_daily_factor_range_arguments(comprehensive_study)
    _add_price_basis_argument(comprehensive_study)

    case_audit = subparsers.add_parser(
        "daily-factor-case-audit",
        help="audit the declared personal low-suction cases before factor discovery",
    )
    _add_daily_factor_range_arguments(case_audit)
    case_audit.add_argument(
        "--price-basis",
        choices=("raw_unadjusted",),
        default="raw_unadjusted",
    )

    extended_discovery = subparsers.add_parser(
        "daily-factor-extended-discovery",
        help="run preregistered MA timing/support/volume discovery",
    )
    _add_daily_factor_range_arguments(extended_discovery)
    _add_price_basis_argument(extended_discovery)
    extended_discovery.add_argument(
        "--frozen-rule",
        action="append",
        default=[],
        metavar="SETUP_TYPE=RULE_KEY",
        help="replay one recent-half-year rule for each setup type",
    )
    extended_discovery.add_argument(
        "--skip-exit-probes",
        action="store_true",
        help="skip close-only exit enumeration during preliminary discovery",
    )

    daily_backtest = subparsers.add_parser(
        "low-suction-daily-backtest",
        help="run the source-rule low-suction daily backtest and store its report",
    )
    _add_daily_factor_range_arguments(daily_backtest)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a read-only daily-factor command and render its result."""

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "daily-factor-audit":
        from .daily_factor_repository import audit_daily_factor_inputs

        report = audit_daily_factor_inputs(start_date=args.start, end_date=args.end)
        rendered = (
            json.dumps(report, ensure_ascii=False, indent=2, default=str)
            if args.format == "json"
            else _render_daily_factor_audit_markdown(report)
        )
    elif args.command == "daily-factor-study":
        from .daily_factor_repository import load_daily_factor_inputs
        from .daily_factor_research import (
            render_daily_factor_json,
            render_daily_factor_markdown,
            run_daily_factor_study,
        )

        inputs = load_daily_factor_inputs(
            start_date=args.start,
            end_date=args.end,
            price_basis=args.price_basis,
        )
        report = run_daily_factor_study(
            bars=inputs.bars.to_dict(orient="records"),
            market_calendar=inputs.market_calendar,
            security_status=inputs.security_status.to_dict(orient="records"),
            evidence_level=inputs.evidence_level,
            blockers=inputs.blockers,
            coverage=inputs.coverage,
            input_sha256=inputs.input_sha256,
        )
        rendered = (
            render_daily_factor_json(report)
            if args.format == "json"
            else render_daily_factor_markdown(report)
        )
    elif args.command == "daily-factor-comprehensive-study":
        from .daily_factor_comprehensive_study import (
            render_comprehensive_daily_factor_json,
            render_comprehensive_daily_factor_markdown,
            run_comprehensive_daily_factor_study,
        )
        from .daily_factor_repository import load_daily_factor_inputs

        inputs = load_daily_factor_inputs(
            start_date=args.start,
            end_date=args.end,
            price_basis=args.price_basis,
        )
        report = run_comprehensive_daily_factor_study(
            bars=inputs.bars.to_dict(orient="records"),
            market_calendar=inputs.market_calendar,
            security_status=inputs.security_status.to_dict(orient="records"),
            evidence_level=inputs.evidence_level,
            blockers=inputs.blockers,
            coverage=inputs.coverage,
            input_sha256=inputs.input_sha256,
        )
        rendered = (
            render_comprehensive_daily_factor_json(report)
            if args.format == "json"
            else render_comprehensive_daily_factor_markdown(report)
        )
    elif args.command == "daily-factor-case-audit":
        from .daily_factor_case_gate import (
            render_personal_case_gate_json,
            render_personal_case_gate_markdown,
            run_personal_case_gate,
        )
        from .daily_factor_comprehensive_study import PERSONAL_CASES
        from .daily_factor_repository import load_daily_factor_inputs

        inputs = load_daily_factor_inputs(
            start_date=args.start,
            end_date=args.end,
            price_basis=args.price_basis,
            vt_symbols=tuple(sorted({case.vt_symbol for case in PERSONAL_CASES})),
        )
        report = run_personal_case_gate(
            bars=inputs.bars.to_dict(orient="records"),
            market_calendar=inputs.market_calendar,
            evidence_level=inputs.evidence_level,
            blockers=inputs.blockers,
            coverage=inputs.coverage,
            input_sha256=inputs.input_sha256,
        )
        rendered = (
            render_personal_case_gate_json(report)
            if args.format == "json"
            else render_personal_case_gate_markdown(report)
        )
    elif args.command == "daily-factor-extended-discovery":
        from .daily_factor_extended_discovery import (
            render_extended_daily_factor_json,
            render_extended_daily_factor_markdown,
            run_extended_daily_factor_discovery,
        )
        from .daily_factor_repository import load_daily_factor_inputs

        try:
            frozen_rule_keys = _parse_frozen_rule_keys(args.frozen_rule)
        except ValueError as exc:
            parser.error(str(exc))
        inputs = load_daily_factor_inputs(
            start_date=args.start,
            end_date=args.end,
            price_basis=args.price_basis,
        )
        report = run_extended_daily_factor_discovery(
            bars=inputs.bars,
            market_calendar=inputs.market_calendar,
            security_status=inputs.security_status.to_dict(orient="records"),
            evidence_level=inputs.evidence_level,
            blockers=inputs.blockers,
            coverage=inputs.coverage,
            input_sha256=inputs.input_sha256,
            frozen_rule_keys=frozen_rule_keys,
            include_exit_evidence=not args.skip_exit_probes,
        )
        rendered = (
            render_extended_daily_factor_json(report)
            if args.format == "json"
            else render_extended_daily_factor_markdown(report)
        )
    elif args.command == "low-suction-daily-backtest":
        from .daily_picks_backtest import BACKTEST_VERSION, build_backtest_payload
        from .daily_picks_repository import save_daily_backtest_run
        from .daily_picks_scanner import scan_low_suction_candidates
        from .daily_factor_repository import load_daily_factor_inputs

        inputs = load_daily_factor_inputs(
            start_date=args.start,
            end_date=args.end,
            price_basis="raw_unadjusted",
        )
        candidates = scan_low_suction_candidates(
            inputs.bars,
            inputs.market_calendar,
            inputs.security_status.to_dict(orient="records"),
        )
        names = _load_candidate_names({item.vt_symbol for item in candidates})
        payload = build_backtest_payload(
            candidates,
            inputs.market_calendar,
            names=names,
        )
        save_daily_backtest_run(BACKTEST_VERSION, payload)
        rendered = json.dumps(
            {
                "version": BACKTEST_VERSION,
                "coverage": payload["coverage"],
                "families": payload["families"],
                "position_sim": {
                    "trend_pullback": payload["position_sim"]["trend_pullback"],  # type: ignore[index]
                    "oversold_rebound": payload["position_sim"]["oversold_rebound"],  # type: ignore[index]
                    "combined": payload["position_sim"]["combined"],  # type: ignore[index]
                },
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    else:
        raise ValueError(f"unsupported command: {args.command}")

    return _write_rendered(rendered, args.output)


def _add_daily_factor_range_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", type=Path)


def _add_price_basis_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--price-basis",
        choices=_PRICE_BASES,
        default="raw_unadjusted",
    )


def _parse_frozen_rule_keys(values: Sequence[str]) -> dict[str, str]:
    """Parse repeated setup_type=rule_key values before any database read."""

    frozen_rule_keys: dict[str, str] = {}
    for value in values:
        setup_type, separator, rule_key = str(value).partition("=")
        setup_type = setup_type.strip()
        rule_key = rule_key.strip()
        if not separator or not setup_type or not rule_key:
            raise ValueError(
                "--frozen-rule must use SETUP_TYPE=RULE_KEY, for example "
                "oversold_rebound=m10_m30_near_or_crossed_down"
            )
        if setup_type in frozen_rule_keys:
            raise ValueError(f"duplicate --frozen-rule setup type: {setup_type}")
        frozen_rule_keys[setup_type] = rule_key
    return frozen_rule_keys


def _load_candidate_names(vt_symbols: set[str]) -> dict[str, str]:
    if not vt_symbols:
        return {}
    from sqlalchemy import select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import session_scope

    with session_scope() as session:
        rows = session.execute(
            select(schema.stocks.c.vt_symbol, schema.stocks.c.name).where(
                schema.stocks.c.vt_symbol.in_(tuple(sorted(vt_symbols)))
            )
        ).all()
    return {str(row[0]): str(row[1]) for row in rows}


def _write_rendered(rendered: str, output: Path | None) -> int:
    if output is None:
        print(rendered, end="" if rendered.endswith("\n") else "\n")
        return 0

    output_path = _validated_output_path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    print(output_path)
    return 0


def _validated_output_path(output: Path) -> Path:
    repository_root = Path(__file__).resolve().parents[4]
    candidate = output if output.is_absolute() else repository_root / output
    resolved = candidate.resolve()
    if "memory" in resolved.parts:
        raise ValueError("memory/ is retired; omit --output to print the report")
    return resolved


def _render_daily_factor_audit_markdown(report: Mapping[str, object]) -> str:
    calendar = report.get("market_calendar")
    adjusted = report.get("adjusted_prices")
    security = report.get("security_status")
    lines = [
        "# 日线低吸数据审计",
        "",
        f"- 证据等级：`{report.get('evidence_level', '-')}`",
    ]
    if isinstance(calendar, Mapping):
        lines.append(
            "- 市场日历：{start} 至 {end}，{days} 个交易日".format(
                start=calendar.get("start", "-"),
                end=calendar.get("end", "-"),
                days=calendar.get("trade_days", 0),
            )
        )
    if isinstance(adjusted, Mapping):
        lines.append(
            "- qfq 范围：{complete}/{total} 当前完整，持久化可用：{ready}".format(
                complete=adjusted.get("complete_scope_count", 0),
                total=adjusted.get("scope_count", 0),
                ready=adjusted.get("ready", False),
            )
        )
        missing = adjusted.get("missing_or_stale_scope_dates")
        if isinstance(missing, Sequence) and missing:
            lines.append(f"- 缺失或失效日期数：{len(missing)}")
    if isinstance(security, Mapping):
        lines.append(f"- 历史证券状态：`{security.get('status', '-')}`")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
