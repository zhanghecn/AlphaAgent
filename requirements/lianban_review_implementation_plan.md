# 连板复盘一期实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 上线 `/lianban` 每日连板复盘页：盘后归档定版、盘中实时滚动、历史日期可回看，功能界面对齐 lianban.net/days。

**Architecture:** 双口径数据层——东财涨停池五池盘后落库（`limit_up_pool_snapshots`，盘口细节+近3周回补）+ 日线重建全历史连板序列（`stock_limit_up_daily`，晋级率统计基础）；统计卡复用现有 `mainline_sentiment_history` 每日预计算；服务层 `services/lianban/` 聚合成单页 payload；前端新顶层页。

**Tech Stack:** FastAPI + SQLAlchemy(Postgres) + akshare（容器内）+ React/TS + vitest；后端测试宿主机 `pytest`（项目根已入 sys.path）。

**设计文档:** `requirements/lianban_review_design.md`（含实证结论，先读）

**提交规则:** 项目规定不自动 `git commit`；每个任务结束=检查点汇报，经用户确认后提交到 master。

---

## 关键既有事实（执行者必读）

- 东财五池已接入：`AkShareAdapter().limit_up_pools(trade_date=None)` → `{zt, zt_previous, strong, zbgc, dtgc}`，
  每行已规范化：`vt_symbol/name/close_price/change_pct/limit_up_price/volume_ratio/turnover_rate/first_limit_time/last_limit_time/limit_up_count/limit_amount/raw`；
  `raw` 内有中文原字段：`炸板次数`、`涨停统计`("13/9")、`所属行业`、`成交额`。
  实现：`alphaagent/data_sources/akshare_adapter.py:1718`(`_limit_up_pools_uncached`)、`:4694`(`_zt_pool_row_to_api`)。
- 东财池**不含 ST**；只有 ~3 周历史；`stock_zt_pool_em(date='YYYYMMDD')` 支持窗口内任意交易日。
- 涨停判定定稿规则（08-12 实盘对账 ≥98%）：收盘价**精确命中**理论涨停价（容差 1e-6）；
  幅度档 创业板(300/301)20%（2020-08-24 前 10%）、科创(688/689)20%、北交所(8/4/920)30%、主板10%、主板ST 5%；
  **收盘价超过 5% 档理论价自动升 10% 档判定**（ST 状态切换日）；一字板 `open==high==low==close`；无昨收（新股）跳过。
- 情绪周期每日预计算已存在：`mainline_sentiment_history.points[]`，字段
  `date/score/phase/phase_label/rise_count/fall_count/flat_count/total_stocks/limit_up_count/limit_down_count/max_limit_up_streak/failed_limit_up_count/previous_limit_up_count/promoted_limit_up_count/promotion_rate/shadow{...}`。
  phase 枚举：`ice冰点/repair修复/divergence分歧/climax高潮/ebb退潮`（`api/mainline_replay.py:1310-1350`）。
  **复盘页统计卡多数指标从这里读，历史日期开箱即有。**
- 同步任务注册四处必须同步改：`DEFAULT_JOBS`（定义）、`JOB_CADENCES`（档级）、`JOB_RUNNERS`（方法名映射）、
  `DEFAULT_BATCH_SCHEDULES["eod_1900"].job_ids`（挂盘后链，位置在 `sync_stock_daily_bars` 之后），
  展示顺序 `_RECOMMENDED_PRIORITY`。文件：`alphaagent/server/services/data_sync.py`。
- 盘后档是 **eod_1900（19:00）**，不是 18:00。
- 测试布局：后端 `tests/alphaagent/services/lianban/`（新建）；前端 `*.spec.tsx` 与页面同目录（vitest）。
- 容器内无 pytest；宿主机 `pytest` 9.0.3 可用，akshare 在宿主机不可用——**测试中禁止 import akshare 顶层模块**
  （适配器是函数内 `importlib.import_module`，mock 时 patch `AkShareAdapter.limit_up_pools`）。
- `is_eligible_main_board(vt_symbol, name)` 在 `services/a_share_universe.py`（首板页在用的主板非ST过滤）。

---

## Phase A · 数据基建

### Task A1: 两张新表 schema

**Files:**
- Modify: `alphaagent/server/db/schema.py`（加表，放在 `stock_lhb_records` 之后）
- Test: `tests/alphaagent/services/lianban/test_schema.py`（新建目录）

**Step 1: 失败测试**

```python
# tests/alphaagent/services/lianban/test_schema.py
from alphaagent.server.db import schema

def test_limit_up_tables_exist():
    assert "limit_up_pool_snapshots" in schema.metadata.tables
    assert "stock_limit_up_daily" in schema.metadata.tables
    t = schema.metadata.tables["limit_up_pool_snapshots"]
    assert {c.name for c in t.primary_key.columns} == {"trade_date", "pool_type", "vt_symbol"}
    d = schema.metadata.tables["stock_limit_up_daily"]
    assert {c.name for c in d.primary_key.columns} == {"trade_date", "vt_symbol"}
```

**Step 2: 跑测试确认失败** `pytest tests/alphaagent/services/lianban/test_schema.py -v` → FAIL

**Step 3: 实现**（参照 schema.py 现有 Table 风格）

```python
limit_up_pool_snapshots = Table(
    "limit_up_pool_snapshots", metadata,
    Column("trade_date", Date, primary_key=True),
    Column("pool_type", String(16), primary_key=True),  # zt/zbgc/dtgc/zt_previous/strong
    Column("vt_symbol", String(32), primary_key=True),
    Column("name", String(80), nullable=False),
    Column("close_price", Float), Column("change_pct", Float),
    Column("turnover_rate", Float), Column("volume_ratio", Float),
    Column("limit_amount", Float),          # 封板资金
    Column("first_limit_time", String(8)),  # HH:MM:SS
    Column("last_limit_time", String(8)),
    Column("break_count", Integer),         # 炸板次数
    Column("limit_stat_days", Integer),     # "13/9" -> 13
    Column("limit_stat_boards", Integer),   # "13/9" -> 9
    Column("limit_up_count", Integer),      # 连板数
    Column("industry", String(120)),        # 东财所属行业
    Column("amount", Float),                # 成交额(raw.成交额)
    Column("source", String(160), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index("ix_limit_up_pool_snapshots_date_type", limit_up_pool_snapshots.c.trade_date, limit_up_pool_snapshots.c.pool_type)

stock_limit_up_daily = Table(
    "stock_limit_up_daily", metadata,
    Column("trade_date", Date, primary_key=True),
    Column("vt_symbol", String(32), primary_key=True),
    Column("is_limit_up", Boolean, nullable=False),
    Column("limit_up_count", Integer, nullable=False, server_default="0"),
    Column("is_one_word", Boolean, nullable=False, server_default="false"),
    Column("is_st", Boolean, nullable=False, server_default="false"),
    Column("board", String(8), nullable=False),   # main/cyb/kcb/bse
    Column("limit_price", Float), Column("prev_close", Float),
    Column("close_price", Float), Column("change_pct", Float),
    Column("touched_limit", Boolean, nullable=False, server_default="false"),  # 盘中摸板(=炸板候选)
    Column("source", String(160), nullable=False, server_default="daily_rebuild"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index("ix_stock_limit_up_daily_date", stock_limit_up_daily.c.trade_date)
Index("ix_stock_limit_up_daily_symbol_date", stock_limit_up_daily.c.vt_symbol, stock_limit_up_daily.c.trade_date)
```

`touched_limit`（当日 high 触及涨停价但收盘未封）供炸板统计日线口径用。

**重要（已实施确认）**：`limit_up_pool_snapshots` 复用了 7a6e95d9 退役旧产品的表名，必须同步从
`alphaagent/server/db/legacy_product_cleanup.py` 的 LEGACY_TABLES 和
`tests/alphaagent/test_legacy_product_removal.py` 的镜像集合中各删一行——否则
create_schema 每次启动先 drop 再 create，新表数据必丢。

**Step 4: 跑测试确认通过**；再跑 `pytest tests/alphaagent -k data_health -q` 确认无副作用。

**Step 5: 检查点**（汇报，确认后提交 `feat(lianban): add limit-up archive tables`）

---

### Task A2: 涨停判定器 `detector.py`

**Files:**
- Create: `alphaagent/server/services/lianban/__init__.py`（空）
- Create: `alphaagent/server/services/lianban/detector.py`
- Test: `tests/alphaagent/services/lianban/test_detector.py`

**Step 1: 失败测试**——用 08-12 实盘对账中固化的案例：

```python
from datetime import date
from alphaagent.server.services.lianban.detector import classify_limit_up

D = date(2026, 8, 12)

def test_main_board_exact_hit():
    # 开开实业: prev=15.70 close=17.27 主板10%
    r = classify_limit_up(symbol="600272", name="开开实业", prev_close=15.70,
                          open_price=17.27, close_price=17.27, high_price=17.27, trade_date=D)
    assert r.is_limit_up and r.board == "main" and r.limit_price == 17.27 and r.is_one_word

def test_cyb_20pct():
    r = classify_limit_up(symbol="300862", name="蓝盾光电", prev_close=27.37,
                          open_price=30.0, close_price=32.84, high_price=32.84, trade_date=D)
    assert r.is_limit_up and r.board == "cyb" and r.limit_price == 32.84

def test_st_main_5pct():
    r = classify_limit_up(symbol="002052", name="ST同洲", prev_close=10.00,
                          open_price=10.2, close_price=10.50, high_price=10.50, trade_date=D)
    assert r.is_limit_up and r.limit_price == 10.50

def test_st_cyb_is_20pct_not_5pct():
    # ST迪威迅(300167) pct=14.16%: 5%档会误判,20%档正确不涨停
    r = classify_limit_up(symbol="300167", name="ST迪威迅", prev_close=4.39,
                          open_price=4.5, close_price=5.01, high_price=5.05, trade_date=D)
    assert not r.is_limit_up

def test_st_switch_day_promotes_to_10pct():
    # ST金鸿(000669) prev=3.54 close=3.89: 超5%档价3.72,精确命中10%档3.89 → 涨停
    r = classify_limit_up(symbol="000669", name="ST金鸿", prev_close=3.54,
                          open_price=3.7, close_price=3.89, high_price=3.89, trade_date=D)
    assert r.is_limit_up and r.limit_price == 3.89

def test_st_switch_day_over_5pct_but_not_limit():
    # *ST中迪 prev≈10.17 close=10.89(+7.08%): 超5%档,但未命中10%档11.19 → 不涨停
    r = classify_limit_up(symbol="000609", name="*ST中迪", prev_close=10.17,
                          open_price=10.4, close_price=10.89, high_price=11.0, trade_date=D)
    assert not r.is_limit_up

def test_bse_30pct():
    r = classify_limit_up(symbol="920856", name="浩淼科技", prev_close=10.00,
                          open_price=11.0, close_price=13.00, high_price=13.00, trade_date=D)
    assert r.is_limit_up and r.board == "bse"

def test_touched_but_not_sealed():
    r = classify_limit_up(symbol="600000", name="浦发银行", prev_close=10.00,
                          open_price=10.2, close_price=10.5, high_price=11.0, trade_date=D)
    assert not r.is_limit_up and r.touched_limit

def test_no_prev_close_skipped():
    r = classify_limit_up(symbol="600000", name="浦发银行", prev_close=None,
                          open_price=1.0, close_price=2.0, high_price=2.0, trade_date=D)
    assert not r.is_limit_up

def test_cyb_before_20200824_is_10pct():
    r = classify_limit_up(symbol="300001", name="特锐德", prev_close=10.00,
                          open_price=10.5, close_price=11.00, high_price=11.00, trade_date=date(2020, 1, 15))
    assert r.is_limit_up and r.limit_price == 11.00
```

**Step 2: 确认失败** → **Step 3: 实现**

```python
# alphaagent/server/services/lianban/detector.py
"""日线涨停判定(精确命中原则, 08-12 东财池对账定稿)."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date

_EPS = 1e-6

@dataclass(frozen=True)
class LimitUpVerdict:
    is_limit_up: bool
    touched_limit: bool
    is_one_word: bool
    is_st: bool
    board: str          # main/cyb/kcb/bse
    limit_price: float | None

def board_of(symbol: str) -> str:
    if symbol.startswith(("300", "301")): return "cyb"
    if symbol.startswith(("688", "689")): return "kcb"
    if symbol.startswith(("8", "4", "92")): return "bse"
    return "main"

def _ratio_candidates(board: str, is_st: bool, trade_date: date) -> tuple[float, ...]:
    """可能幅度档, 按从低到高; 精确命中任一档即涨停(升档自洽)."""
    if board == "cyb":
        return (0.20,) if trade_date >= date(2020, 8, 24) else (0.10,)
    if board == "kcb": return (0.20,)
    if board == "bse": return (0.30,)
    return (0.05, 0.10) if is_st else (0.10,)

def classify_limit_up(*, symbol, name, prev_close, open_price, close_price, high_price, trade_date) -> LimitUpVerdict:
    board = board_of(symbol)
    is_st = "ST" in (name or "").upper()
    if not prev_close or prev_close <= 0:
        return LimitUpVerdict(False, False, False, is_st, board, None)
    limit_price = None
    is_up = False
    for ratio in _ratio_candidates(board, is_st, trade_date):
        lp = round(prev_close * (1 + ratio) + 1e-9, 2)
        if close_price >= lp - _EPS:
            # 命中本档; 记录并允许继续升档验证(取最终命中的最高档)
            limit_price, is_up = lp, True
        elif is_up:
            break  # 超过低档但未达高档: 以已命中档为准
        else:
            break  # 未达最低档
    # 升档自洽: close 超过5%档价但未达10%档价时, 说明当日非5%限制 → 不涨停
    if is_up and len(_ratio_candidates(board, is_st, trade_date)) == 2:
        hi = round(prev_close * 1.10 + 1e-9, 2)
        if close_price < hi - _EPS and close_price > limit_price + _EPS:
            is_up, limit_price = False, None
        elif close_price >= hi - _EPS:
            limit_price = hi
    touched = False
    if not is_up:
        for ratio in _ratio_candidates(board, is_st, trade_date):
            if high_price >= round(prev_close * (1 + ratio) + 1e-9, 2) - _EPS:
                touched = True
                break
    one_word = bool(is_up and open_price == high_price == close_price)
    return LimitUpVerdict(is_up, touched, one_word, is_st, board, limit_price if is_up else None)
```

注意：实现时先跑通测试，若升档逻辑与测试期望有出入，以测试案例为准微调（这些案例都是实盘对账来的）。

**Step 4: 通过** → **Step 5: 检查点**

---

### Task A3: 全历史重建服务 `rebuild.py` + 任务注册

**Files:**
- Create: `alphaagent/server/services/lianban/rebuild.py`
- Modify: `alphaagent/server/services/data_sync.py`（DEFAULT_JOBS/JOB_CADENCES/JOB_RUNNERS/eod_1900/_RECOMMENDED_PRIORITY）
- Test: `tests/alphaagent/services/lianban/test_rebuild.py`

**Step 1: 失败测试**（内存构造 3 日两只股递推链，断板重算、一字板标记、ST 排除标记）：

```python
def test_rebuild_streak_chain(fake_session):
    # 股A: 3日连板(count 1→2→3); 股B: 涨停→断板→涨停(count 1→0→1)
    rows = [...]
    out = list(iter_limit_up_daily(rows))
    a = {r["trade_date"]: r["limit_up_count"] for r in out if r["vt_symbol"] == "A"}
    assert a == {d1: 1, d2: 2, d3: 3}
```

核心函数设计（纯函数可测，DB 落库薄壳）：

```python
def iter_limit_up_daily(bars: Iterable[BarRow]) -> Iterator[dict]:
    """bars: 按 (vt_symbol, trade_date) 排序的全市场日线。
    逐股递推连板状态; yield stock_limit_up_daily 行(dict)。
    streak 规则: 今日涨停 → 昨streak+1(昨未涨停则1); 今日未涨停 → 0(不写行或写is_limit_up=False)。
    """
```

落库策略：只写 `is_limit_up OR touched_limit OR streak>0 前态` 的行？——决策：**只写涨停行**（年约 6-8 万行/全历史约 150 万行），未涨停日不存，晋级统计用"昨涨停今日无行=断板"推。touched_limit 行单独写（is_limit_up=False, touched_limit=True）供炸板口径。测试里验证。

**Step 2-3: 实现 + 任务注册**

- `run_rebuild(session, trade_date=None, full=False)`：增量模式取 `(vt_symbol, 最近状态)` 续推；全量模式流式扫 `stock_daily_bars`（按 vt_symbol 分组、yield_per(5000)，目标 < 15 分钟；不写日志刷屏）
- job id `rebuild_stock_limit_up_daily`，cadence `CADENCE_EOD_DAILY / CATEGORY_MARKET_BARS`，挂在 eod_1900 的 `sync_stock_daily_bars` 之后；`JOB_RUNNERS` 映射 `_run_rebuild_stock_limit_up_daily`

**Step 4: 通过 + 全量测试无副作用** → **Step 5: 检查点**

---

### Task A4: 五池归档服务 `archive.py` + 盘后任务

**Files:**
- Create: `alphaagent/server/services/lianban/archive.py`
- Modify: `alphaagent/server/services/data_sync.py`
- Test: `tests/alphaagent/services/lianban/test_archive.py`

**Step 1: 失败测试**（patch `AkShareAdapter.limit_up_pools`，验证：五池分类落库、`涨停统计` "13/9" 解析成 days=13/boards=9、`炸板次数`→break_count、幂等重跑不重复）：

```python
def test_archive_parses_limit_stat_and_is_idempotent(fake_session, monkeypatch):
    monkeypatch.setattr(AkShareAdapter, "limit_up_pools", lambda self, trade_date=None: FAKE_POOLS)
    n1 = archive_daily_pools(fake_session, date(2026, 8, 12))
    n2 = archive_daily_pools(fake_session, date(2026, 8, 12))
    assert n1 == n2  # 幂等: delete+insert
    row = get_row(fake_session, "zt", "600602.SSE")
    assert row.limit_stat_days == 1 and row.limit_stat_boards == 1
```

**Step 3: 实现要点**
- `archive_daily_pools(session, trade_date)`：调适配器 → 五池逐池 delete 当日+insert；`first_limit_time` 规范成 `HH:MM:SS`（复用 `_time_text` 逻辑，提取共享 helper）
- 非交易日东财返回空 → 记 `sync_job_runs` 成功但 0 行（不报错）
- job id `sync_limit_up_pool_snapshots`，挂 eod_1900 链（`sync_stock_daily_bars` 之后、`rebuild_stock_limit_up_daily` 之前——归档与重建独立但同日）

**Step 5: 检查点**

---

### Task A5: 近3周回补

**Files:** Create `alphaagent/server/services/lianban/backfill.py`；Test `tests/alphaagent/services/lianban/test_backfill.py`

- `backfill_pool_snapshots(session, days=25)`：从 `stock_daily_bars` 取最近 25 个交易日，逐日调 A4 的 `archive_daily_pools`（幂等），日级 sleep 1s 防东财限流；已归档日跳过（查 `limit_up_pool_snapshots` distinct date）
- 注册为手动 job `backfill_limit_up_pool_snapshots`（不进定时档，运维触发）
- 测试：mock 归档函数，验证交易日序列正确、已归档跳过

**检查点**

---

### Task A6: 双口径对账 `parity.py`

**Files:** Create `alphaagent/server/services/lianban/parity.py`；Test `tests/alphaagent/services/lianban/test_parity.py`

- `parity_report(session, trade_date)`：东财 zt 池名单（非ST天然）vs `stock_limit_up_daily` 当日 `is_limit_up AND NOT is_st` 名单 → `{em_only:[...], daily_only:[...], matched:n, diff_count}`
- 测试：构造两边名单验证 diff 输出
- 接数据健康：复用现有 data_health 体系（参照 `tests/alphaagent/test_data_health.py` 的断言方式），diff > 2 只在健康接口里标 warning

**检查点**

---

### Task A7: 融资余额 `sync_margin_balance`

**Files:** Create `alphaagent/server/services/lianban/margin.py`；Modify `schema.py`（新表 `market_margin_balance: trade_date PK, margin_balance float, source, raw`）；Modify `data_sync.py`

- akshare 接口：`ak.stock_margin_sse(start_date, end_date)`（信用交易日期/融资余额）+ `ak.stock_margin_szse(date)` 合并两市；容器内先实拉验证字段名再定稿
- job `sync_margin_balance`，挂 eod_1900 尾部（东财/交易所晚间公布）
- 测试：mock 两个接口 DataFrame，验证合并与幂等

**检查点**

---

### Task A8: 历史准确性抽查（妖股断言）

**Files:** Test `tests/alphaagent/services/lianban/test_known_streaks.py`

- 依赖 A3 全量重建完成后，对已知案例断言（连板数以公开复盘为准）：
  2025-09 天普股份 15 连板、2025-10 ST中迪 22 连板（ST 口径）、2026-08-13 秦安股份 5 连板
- 用例跑在本地开发库（标记 `@pytest.mark.localdb`，CI 无库自动 skip——参照现有测试有没有类似模式，没有就用 `pytest.importorskip`+连接探测封装）
- 这一步同时是**给用户的准确性交付证据**

**检查点**

---

## Phase B · 服务与 API

### Task B1: 梯队构建 `ladder.py`

**Files:** Create `alphaagent/server/services/lianban/ladder.py`；Test 同名

- `build_ladder(session, trade_date) -> LadderPayload`：
  - 定版模式：`limit_up_pool_snapshots` 当日 zt 行，按 `limit_up_count` 降序分档；
    个股行 `{vt_symbol,name,limit_up_count,first_limit_time,limit_stat_days,limit_stat_boards,is_reverse(=boards>limit_up_count),industry,concepts[]}`
  - concepts 从 `stock_sector_memberships`+`sectors`（concept 类）取，每股最多 3 个
  - 历史日期（归档缺失）降级：`stock_limit_up_daily` 重建档（无封板时间/封单，字段 null，`source="daily_rebuild"`）
  - 每档附：`count`、`today_promotion`（昨 X 板今日 X+1 的实际比例，跨日 join 算）
- 测试：构造两日归档行，验证分档、is_reverse（一鸣 13/9 连板4 → True；秦安 5/5 连板5 → False）、today_promotion 计算

### Task B2: 晋级率统计 `promotion.py`

**Files:** Create `alphaagent/server/services/lianban/promotion.py`；Test 同名

- `promotion_stats(session, trade_date, lookback=250)`：从 `stock_limit_up_daily`（NOT is_st 口径）算：
  - 每板位「明日晋级率」= 近 250 日中 streak==N 且次日 streak==N+1 的频率（N=1..8）
  - 首板晋级率当日实际（昨 streak1 今日 streak2 / 昨 streak1 总数）+ 历史均值
  - 五日接力矩阵：近 5 日各板位家数演变
- SQL 实现（窗口函数 lead/streak join），单日查询 < 100ms；结果随 rebuild 后可加进程缓存
- 测试：构造 10 日已知梯队序列，断言 1进2、2进3 频率精确值

### Task B3: 复盘聚合 `review.py`

**Files:** Create `alphaagent/server/services/lianban/review.py`；Test 同名

- `build_review(session, trade_date) -> dict` 单页 payload：
  - `mode`: live（今日未定版）/ final（定版）/ rebuild（历史降级）
  - `indices`：六指数涨跌幅（`stock_daily_bars` 指数行；缺北证50 则从适配器指数接口补，mock 测）
  - `stats`：优先读 `mainline_sentiment_history.points` 对应该日（涨停/跌停/涨跌家数/情绪 score+phase_label）；
    涨停/连板/最高板/炸板/封板率改从归档/ladder 取（东财口径对齐 lianban）；昨对比=前一交易日同口径
  - `prev_day_performance`：昨 zt_previous 名单 × 今日日线 change_pct → 均值/中位/翻红率；逐只状态（晋级/炸板/断板）
  - `themes`：按 industry 分组（家数、龙头=连板最高/同板首封最早、个股按 first_limit_time 排序）；
    资金强度条从 `sector_fund_flows` 当日主力净额 Top10
  - `hot_leaders`：`stock_hot_ranks` 最新榜 join 连板/涨幅
  - `broken`：zbgc 池列表（首封时间+炸板次数）
  - `margin_balance`：A7 表最新两行（值+较前日）
- 测试：全 mock 数据源，断言 payload 骨架与关键计算（封板率=zt/(zt+zbgc) 等）

### Task B4: API `/api/lianban/*`

**Files:** Create `alphaagent/server/api/lianban.py`；Modify `alphaagent/server/api/router.py`；Test `tests/alphaagent/services/lianban/test_api.py`

- `GET /api/lianban/review?date=`（缺省=最近交易日）：调 B3；错误参照 first_board 的 `ok/fail` 包装
- `GET /api/lianban/dates`：有归档或有 sentiment point 的交易日列表（降序，limit 400）
- live 模式判断：date==今日且 `limit_up_pool_snapshots` 今日无行 → live（调适配器实时池喂 ladder，复用首板页通道）；否则归档
- 契约测试：TestClient 打两个端点，mock service 层，断言 200 结构与日期非法 422

**检查点（Phase B 结束=后端自测全部通过，API 可 curl）**

---

## Phase C · 前端 `/lianban`

设计约束：v3.1 终端蓝设计系统；**零动画铁律**；数字 JetBrains Mono（项目已有 `tabular-nums`/mono 工具类）；涨跌红绿语义色；复用 `StockIdentityLink`、`EmptyState`、`LoadingState`、`formatPct/formatAmount`。

### Task C1: api client + 路由 + 侧栏

- Create `frontend/src/api/lianban.ts`（类型对齐 B4 payload，`fetchLianbanReview(date?)`、`fetchLianbanDates()`）
- Modify `frontend/src/App.tsx`（`/lianban` 路由）+ 侧栏导航组件（找 AppShell 的 nav 配置，加「连板复盘」，图标 `Layers`）
- Test `frontend/src/api/lianban.spec.ts`：mock client 断言 URL 拼接

### Task C2: 页头（日期导航+指数条+模式徽标）

- `LianbanReviewPage.tsx` 骨架 + `ReviewHeader`：←前一天/日期选择（归档日期下拉）/已是最新；六指数条；`mode=live` 时「盘中滚动·未定版」徽标 + 30s refetch（对齐首板页模式）
- spec：模式徽标文案、日期导航边界（首日禁用←）

### Task C3: 统计卡组 `ReviewStatsCards`

- 12 卡：涨停(昨)/连板(昨)/最高板(昨)/跌停(昨)/封板率(昨)/炸板(昨)/昨涨停今表现(均值·中位·翻红)/情绪周期(phase_label·score)/涨跌家数(红盘比)/63日新高新低/两市成交/融资余额
- 新高新低：B3 里从 sentiment points 没有，需在 B3 用日线补算（`close>=rolling max(high,63)` 当日计数——在 review.py 里 SQL 窗口函数算好，前端只展示）
- spec：格式化与昨对比箭头

### Task C4: 连板天梯 `LadderSection`（核心组件）

- 板位降序档卡：档头（N板·家数·今日X进Y实际·明日晋级率≈）；个股行（首封时间 mono、名称链接、「反·N天M板」徽标、题材标签）
- spec：is_reverse 徽标渲染、档排序、空档不渲染

### Task C5: 梯队接力 + 炸板列表

- `RelaySection`：昨日各板位个股今日表现行（晋级标「晋N板」绿、断板灰、涨幅语义色）；首板晋级率+历史均值
- `BrokenBoardsSection`：炸板行（首封时间+炸N次）
- spec：晋级状态映射

### Task C6: 热点题材 + 人气龙头

- `ThemeGroupsSection`：题材组卡（编号+名称+家数+龙头★+个股按首封时间列）；展开收起（默认前8组，对齐 lianban「展开剩余」）
- `HotLeadersSection`：热榜 Top10（排名+名称+连板徽标+涨幅）
- spec：排序与龙头标记

### Task C7: 整页联调 + 页面 spec

- FAQ 静态区 + 归档导航；`LianbanReviewPage.spec.tsx`（mock api，断言区块渲染顺序与 live 模式轮询注册）
- `npm run test` + `npm run build` 全绿

**检查点（Phase C 结束=页面本地可用）**

---

## Phase D · 验收（对账单）

### Task D1: lianban 逐项对账

- 抓 lianban 08-12、08-13 页面（curl 直连法），与我们 `/api/lianban/review?date=` 输出逐项比对：
  涨停/连板/最高板/跌停/封板率/炸板家数、天梯各档家数与个股、炸板名单、题材分组
- 差异写验收清单（预期差异仅限：情绪阶段口径、明日晋级率数值[我们 250 日口径]、📅N天标记[二期]、驱动逻辑文案[二期]）

### Task D2: 盘中实时演练

- 交易日盘中打开 `/lianban`：live 模式 30s 刷新、模式徽标、与首板页涨停池数字互证；15:00 后「收盘数据整理中」；19:00 档后定版

### Task D3: 性能验证

- 历史页 API P95 < 100ms（`curl -w` 实测 10 次取 P95）；归档日期接口 < 50ms；全量 rebuild 时长记录进数据健康

---

## 执行顺序与依赖

```
A1 → A2 → A3 → A4 → A5 ─┐
      ↓        ↓         ├→ A6(对账) → A8(抽查)
      A7(独立) ──────────┘
A2+A3 → B1 → B2 → B3 → B4 → C1..C7 → D1..D3
```

A7 与主线独立可并行；C 只依赖 B4 的 payload 结构（可先 mock 开发）。
