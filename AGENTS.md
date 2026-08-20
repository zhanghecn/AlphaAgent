# Project Context for Codex

This repository is AlphaAgent, an A-share quantitative trading and agent research
system built on VeighNa/vn.py 4.4.0. Before adding scripts, docs, or source changes,
read this file and verify against the local code/docs when needed.

## User Context

- The user is learning A-share quantitative trading and wants to build an A-share
  focused system on top of this project.
- The long-term direction is a server-side A-share quant platform with automated
  research, intelligent stock selection, strategy execution, and agent-assisted
  trading workflows.
- The user prefers project-source/documentation-driven work, not ad hoc scripts first.
- Explain in Chinese unless the user asks otherwise.
- Be conservative with source edits. Do not modify `vnpy/` or official examples unless
  the change is explicitly required.
- Deliver research, diagnostics, and implementation results directly in the conversation.
  Do not maintain a project-local memory archive, diary, or duplicate report store.
- The project/product name is `AlphaAgent`. Keep the internal Python package name
  `vnpy` for now to preserve compatibility with vn.py plugins and imports.
- Do not run `git commit` or `git push` unless the user explicitly asks for it.
- For Docker, deployment, and release architecture, use `~/project/ai/sub2api` as
  the local reference project. Keep the operator/developer entrypoint simple
  (`docker compose up --build` for local development, Compose files under
  `deploy/` for deployment) and put build/release complexity into Dockerfile,
  Compose, deploy scripts, and CI instead of asking users to remember special
  build target commands.
- Use Docker Compose for all frontend and full-stack runs. Do not start a
  standalone Vite/Node development server or expose port 5173; verify the web
  application through the Compose gateway instead.
- Docker release shape: root `docker-compose.yml` is for local development;
  `deploy/docker-compose.local.yml` is for server deployment with local data
  directories; `.github/workflows/docker-release.yml` publishes
  `ghcr.io/zhanghecn/alphaagent-api` and `ghcr.io/zhanghecn/alphaagent-web` on
  `v*` tags. Do not reintroduce manual dependency-build instructions for normal
  users.

## Repository Layout

- `vnpy/`: inherited vn.py core framework package. Do not rename casually.
  - `vnpy/trader/`: event-driven trading core, gateway/datafeed/database abstraction,
    UI framework, object models, settings.
  - `vnpy/event/`: event engine.
  - `vnpy/chart/`: chart widgets.
  - `vnpy/alpha/`: multi-factor/ML research workflow for local research, including
    dataset, model, strategy, and `AlphaLab`.
  - `vnpy/rpc/`: RPC support.
- `docs/`: official local documentation.
  - `docs/community/info/`: core concepts such as introduction, gateway, datafeed,
    database, Alpha.
  - `docs/community/app/`: app module manuals such as DataManager, ScriptTrader,
    DataRecorder, CTA Strategy, Portfolio Strategy.
  - `docs/elite/` and `docs/fusion/`: paid/advanced/Fusion documentation.
- `examples/`: official examples.
  - `examples/veighna_trader/run.py`: desktop Trader launcher.
  - `examples/download_bars/download_bars.ipynb`: Datafeed -> Database historical bar
    download example.
  - `examples/alpha_research/`: A-share oriented Alpha research notebooks using RQData
    or XT data examples.
- `tests/`: pytest tests.
- `pyproject.toml`: project metadata and dependencies.
- `requirements/`: product requirements and requirement analysis documents.
  - `requirements/alphaagent_requirement_map.md`: raw requirement map.
  - `requirements/alphaagent_functional_design.md`: functional modules and execution flow.
  - `requirements/alphaagent_service_frontend_execution_plan.md`: backend/frontend execution plan and API contract draft.

## Current Environment Snapshot

Checked with local imports:

- Installed: `vnpy`, `vnpy_ctp`, `vnpy_ctastrategy`, `vnpy_ctabacktester`,
  `vnpy_datamanager`, `vnpy_sqlite`.
- Missing A-share/data plugins: `vnpy_xt`, `vnpy_rqdata`, `vnpy_tushare`,
  `vnpy_xtp`, `vnpy_tora`, `vnpy_ost`, `vnpy_emt`.
- Missing useful app plugins: `vnpy_scripttrader`, `vnpy_portfoliostrategy`,
  `vnpy_datarecorder`.

`pyproject.toml` keeps the Python distribution name `vnpy` and source package directory
`vnpy` because official vn.py plugins declare dependencies such as `vnpy>=4.0.0`.
The repository/product name is `AlphaAgent`. `pyproject.toml` also has
`requires-python = ">=3.11"` because `uv sync` with the `dev` extra failed when the
project advertised Python 3.10 support while `scipy-stubs>=1.16.3.0` requires
Python >= 3.11.

## How the Project Runs Now

The current official GUI entry is:

```bash
uv run python examples/veighna_trader/run.py
```

That launcher currently registers:

- Gateway: `CtpGateway` only, for futures/options, not A-shares.
- Apps: `CtaStrategyApp`, `CtaBacktesterApp`, `DataManagerApp`.

The A-share gateway imports in `examples/veighna_trader/run.py` are commented out and
their packages are not installed. Therefore, the current GUI cannot connect to an
A-share broker or show all A-share contracts through an official A-share gateway yet.

## A-share Architecture in This Project

vn.py core does not bundle A-share market data. It provides standard interfaces:

- Gateway: realtime market data, account, positions, orders, trades, contracts.
  - Core API: `vnpy.trader.engine.MainEngine.add_gateway`, `connect`, `subscribe`,
    `send_order`, `query_history`.
  - Base class: `vnpy.trader.gateway.BaseGateway`.
  - Runtime cache: `OmsEngine` stores latest ticks, contracts, orders, trades,
    positions, accounts.
- Datafeed: historical bar/tick data.
  - Core API: `vnpy.trader.datafeed.get_datafeed()`.
  - It reads `SETTINGS["datafeed.name"]` and imports `vnpy_{name}` dynamically.
  - If no datafeed is configured, it returns `BaseDatafeed` and prints that no data
    service is configured.
- Database: local storage for historical data, typically through `vnpy_sqlite`.
- DataManager: GUI app for downloading, importing, viewing, exporting, updating,
  and deleting historical data in the local database.
- AlphaLab: local A-share/multi-factor research data workflow under `vnpy.alpha`.

Officially documented A-share related options:

- Trading gateways:
  - `vnpy_xtp`: A-share, margin trading, ETF options.
  - `vnpy_tora`: A-share and ETF options.
  - `vnpy_ost`: A-share.
  - `vnpy_emt`: A-share.
- Realtime/special quote gateways:
  - `vnpy_rqdata`: cross-market realtime quotes.
  - `vnpy_xt`: cross-market realtime quotes.
- Historical datafeeds:
  - `vnpy_xt`: stocks, futures, options, funds, bonds, contracts, financial data.
  - `vnpy_rqdata`: stocks, futures, options, funds, bonds, gold TD.
  - `vnpy_tushare`: stocks, futures, options, funds; generally more suitable for
    historical/pan-after-close workflows than realtime trading.

For "see all A-shares", the correct vn.py path is not to patch core source. Install and
configure a suitable A-share data/gateway plugin, register it in the launcher, connect
it, wait for contract/query completion, then inspect contracts/ticks through Trader UI,
ScriptTrader, or `MainEngine.get_all_contracts()`/`get_all_ticks()`.

## Must-read Files for A-share Work

Read these before writing new A-share code:

- `README.md`: module list and supported gateways/apps/datafeeds.
- `docs/community/info/introduction.md`: project positioning.
- `docs/community/info/gateway.md`: gateway loading, connection, contract query.
- `docs/community/info/datafeed.md`: datafeed configuration and history query API.
- `docs/community/info/database.md`: local database configuration.
- `docs/community/info/alpha.md`: Alpha expression safety notes.
- `docs/community/app/data_manager.md`: historical data GUI.
- `docs/community/app/data_recorder.md`: realtime tick/bar recording.
- `docs/community/app/script_trader.md`: multi-symbol script trading/scanning.
- `docs/community/app/portfolio_strategy.md`: multi-contract strategy app.
- `examples/veighna_trader/run.py`: current GUI launcher.
- `examples/download_bars/download_bars.ipynb`: official historical data pipeline.
- `examples/alpha_research/download_data_rq.ipynb`: RQData A-share component/history
  download example for AlphaLab.
- `examples/alpha_research/download_data_xt.ipynb`: XT A-share component/history
  download example for AlphaLab.

## Research Reporting and Workspace Notes

- Do not create or use a `memory/` directory. It is intentionally absent.
- Report research findings, backtest tables, diagnosis, decisions, and verification
  directly to the user in the final response. Do not copy those reports into the
  repository merely for agent recall.
- Do not create chronological work logs, chat transcripts, daily notes, or milestone
  diaries anywhere in the repository.
- Create a durable document only when the user explicitly asks for one or when it is a
  real product requirement, operator guide, API contract, or test fixture. Put it in
  the appropriate existing `requirements/`, `docs/`, or `tests/` location and keep it
  focused on the current contract rather than process history.
- For broad project work, read `AGENTS.md`, the relevant source, tests, official local
  docs, and requirement documents directly. Do not rely on accumulated agent notes.

## Local Files to Handle Deliberately

Current non-upstream files/changes observed:

- `pyproject.toml`: Python requirement changed from `>=3.10` to `>=3.11`.
- `pyproject.toml`: project description/homepage/source metadata updated for
  AlphaAgent, while distribution name remains `vnpy` for plugin compatibility.
- `uv.lock`: generated by `uv sync`.

The user complained that files were scattered and source/examples were modified too
casually. Avoid adding more files at repository root except durable context files like
this one. Keep experiments out of official source/example paths unless explicitly
requested, and do not save conversational reports for later agent consumption.

## Working Rules for Future A-share Tasks

- Start from official docs/examples and installed plugin state.
- Do not claim vn.py can show all A-share realtime data until a real A-share data or
  gateway plugin is installed and configured.
- Do not write free-data scripts as the default answer when the user asks how vn.py
  itself works.
- Prefer demonstrating data flow through:
  1. Datafeed configuration and `get_datafeed()`.
  2. DataManager for historical database visibility.
  3. Gateway connection and contract query for realtime/trading visibility.
  4. ScriptTrader or `MainEngine` APIs for multi-symbol scanning and strategy control.
- Keep A-share tutorials tied to concrete project files and API names.
- If using external data services, clearly separate realtime quote, historical data,
  contract list, financial data, and broker trading capabilities.
