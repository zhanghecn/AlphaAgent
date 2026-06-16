# AlphaAgent Dragon Pullback Implementation Plan

Goal: implement a parallel optimized pullback strategy, keep `mainline_leader_pullback` as the baseline, and verify whether optimized buy/sell points improve signal quality and backtest return.

Scope:

- Add `mainline_dragon_pullback / 0.1.0` as a new strategy with default entry score `76`.
- Keep the current four strategies available for comparison.
- Implement the first version on daily bars, using the current D close -> D+1 14:30 execution framework.
- Add strategy-specific trend exit logic for the new strategy so it is not forced through the old fixed 18% full take-profit.
- Add focused unit tests for MA10 support, weak rebound rejection, high-level distribution rejection, registry metadata, and strategy-specific exits.
- Run targeted pytest and at least one persisted or non-persisted strategy comparison/backtest using the local API or service.

Files:

- Create `alphaagent/server/services/quant/strategies/dragon_pullback.py`
- Modify `alphaagent/server/services/quant/factors.py`
- Modify `alphaagent/server/services/quant/strategy_registry.py`
- Modify `alphaagent/server/services/quant/screening_payloads.py`
- Modify `alphaagent/server/services/backtest/simulation.py`
- Modify `tests/alphaagent/test_quant_backtest_portfolio.py`
- Update `requirements/README.md` and `memory/09_decisions/decisions.md` after verification

Verification:

- `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q`
- `uv run pytest tests/alphaagent/test_factors.py -q`
- `uv run python -m compileall alphaagent/server/services/quant alphaagent/server/services/backtest`
- Run a local strategy comparison/backtest for the six named stocks or a main-board sample and record the conclusion.
