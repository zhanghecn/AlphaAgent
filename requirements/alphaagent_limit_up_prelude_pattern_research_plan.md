# 首板前奏形态因子研究 + 回测集成 + 盘前选股 txt 导出（2026-08-02）

> 执行状态：**全部完成**。研究 + 盘前选股 + 回测对照 + 规则说明均已落地。
> 研究证据：`memory/06_backtests/limit_up_leader_first_board_prelude_pattern_20260802.{json,md}`
> （含 Phase 3 回测对照裁决附录）

## 需求（主人 2026-08-02 原话提炼）

主人提出首板前奏形态假说并指定研究→落地链路：

- **A 小阳爬升型**：首板前 2-3 个连续小阳线，每日收盘涨幅 ≤3%（0 < change_pct ≤ 3）
- **B 阴跌蓄势型**（与小阳相反）：低位首板前连续 2-3 个小阴跌，每日跌幅 ≤3%
- **量能共振**：前奏期之前约 7 个交易日量稳，前奏期量能突变；A/B 两型方向有区别
- 成功样本放宽：**>=2 连板即算**（不非要成妖）

研究流程（指定顺序）：收集 >=2 板首板票去重 → 核对形态命中率 → 量能特征分型分析。

落地 4 项：① 扫板回测质量检查 ② 分钟回测质量检查 ③ 规则说明详细讲解特征因子
④ 盘前选股 txt 下载（每行 6 位代码导入同花顺，早盘人工核对涨幅快速打板）。

## 研究裁决（Phase 1 已出结果）

窗口 2025-06-27..2026-07-31，11223 首板 / 2462 个 >=2 板正样本（基线 21.94%）：

| 假说 | 裁决 | 证据 |
|---|---|---|
| A/B 量能方向有区别（A 放量/B 缩量） | **成立**（p<0.0001） | A shift 中位 1.018 / B 0.862（69% 缩量） |
| vol_shift（前奏放量）预测 >=2 板 | **弱成立**（唯一过月度一致性） | AUC 0.5446、一致率 0.857、6/7 月不翻转 |
| A 小阳形态预测 >=2 板 | **弱正效应** | 24.68% vs 基线 21.94%（±2% 严格档 24.65%） |
| B 阴跌形态预测 >=2 板 | **否决** | 成功组命中率 9.18% < 失败组 9.63%；组合 18.65% 低于基线 |
| 形态做硬过滤 | **否决** | 78% 成功首板无前奏形态，整体区分度弱 |

落地形态：盘前人工观察清单（形态+量能特征展示）+ vol_shift 可选进校准池；不做硬过滤。

## 实现清单

### 新建

1. `alphaagent/server/services/limit_up/leader_first_board_prelude_pattern_research.py`
   —— 研究脚本：`_prelude_pattern_features` 共享纯函数（streak/pattern/vol_cv/vol_shift，
   D-1 可观测）+ 五分析块报告；复用 `build_factor_samples(min_consecutive_boards=2,
   board_gap_mode="wave")`
2. `alphaagent/server/services/limit_up/premarket_prelude_service.py`
   —— 盘前选股：`_screen_symbol` 纯函数（主板/低位 return_20d≤10%/D-1 未涨停/形态量能门槛）
   + 60s 缓存 + **快照表读写**（`premarket_prelude_snapshots`，EOD 22:00 批次预算写库，
   API 读库毫秒返回——实时全市场扫描在 0.25 核 api 容器要 30-60s 等不起）
3. `frontend/src/features/limitUp/PremarketCandidatesPanel.tsx`
   —— 盘前候选面板（形态徽章/量比/量稳/概念）+ 同花顺 txt 下载按钮
4. 测试：`test_limit_up_prelude_pattern_research.py`（22）、
   `test_limit_up_premarket_prelude_service.py`（22）

### 修改

5. `leader_minute_backtest.py`：`_d1_factors` 加前奏特征（分钟+扫板+dump 一处生效）；
   `require_prelude_pattern`（none/any/small_yang/small_yin 硬滤，默认关）+
   `include_prelude_factors_in_calibration`（校准池扩 4 键，默认关）+ CLI
6. `api/limit_up.py`：`GET /limit-up/premarket/prelude-candidates`（JSON，读快照优先）
   + `.txt`（PlainTextResponse + Content-Disposition，每行 6 位代码——仓内首个文件下载端点）
7. `data_sync.py`：`premarket_prelude_snapshot` batch job 挂 eod_backtest_2200（回测重跑后顺路算）
8. `schema.py`：`premarket_prelude_snapshots` 表（trade_date PK + payload JSONB）
9. 前端 `limitUp.ts`：fetch + download（authFetch + Blob + a[download]，仓内首个下载实现）；
   `FirstBoardLeaderPage.tsx` 实时推荐视图嵌面板；
   `ruleFlow.ts` 第 ⑨ 节点「盘前前奏形态筛选（研究验证中）」+ spec 同步

## Phase 3 回测对照裁决（已完成，2026-08-02 凌晨）

分钟回填完成（44 天 2892-3206 票/日），对照矩阵（全 `--skip-save`）结果：

| 模式 | 版本 | 复利 | 胜率 | PF | 裁决 |
|---|---|---:|---:|---:|---|
| 分钟 | 基线（v5b 无门） | +16.4% | 53.1% | 1.16 | — |
| 分钟 | +前奏校准池 | +1.4% | 53.1% | 1.01 | ❌ 稀释有效因子（7 月 -18.6k→-33.6k） |
| 分钟 | +形态硬滤 any | -11.8% | 40.0% | 0.66 | ❌ 砍 99.8% 候选自残 |
| 扫板 | 基线 | -56.1% | 33.6% | 0.44 | 两月全亏，结构性负期望终锤 |
| 扫板 | +前奏校准池 | -56.1% | 33.6% | 0.44 | ≡ 零效果（校准未生效） |
| 扫板 | +形态硬滤 any | -20.3% | 28.4% | 0.54 | ❌ 少亏只因少交易 |

**裁决：前奏因子不进回测生产**（参数保留默认关）；分钟级 v5b 触板前动量买入
仍是唯一正期望入口；前奏形态的正确形态 = 盘前人工观察清单（已上线）。

## Phase 5 主人版低位首板观察池（2026-08-02 午，最终落地形态）

主人指令：只要低位首板（锚点：立新能源/爱丽家居/传智教育=低位，至纯科技=非低位）。
召回核对（266 天 2442 只主板 >=2 板票）：现有过滤链召回 73-81%，漏网 100% 深跌排除，
误杀不可分；单条件浓缩全失败（板块 Top100 召回仅 8%）。

**低位四条件定稿（v2''）**：① 距 126 日高点回撤 ≥25%（跌得深）② 距 126 日低点
反弹 ≤12%（离底近）③ 近 5 日涨幅 ≤6%（无急反弹）④ 近 20 日振幅 ≤40%（底部平稳）。
至纯科技迭代案例：07-31 深 V 急反弹（reb 14.5%/ret5d +8.4%/振幅 90%）被③④卡排除
（主人：「这种不算低位，看前 30 日与均线」；锚点振幅 21-34% 全通过）。
07-31 快照实盘验证：低位池 389 只、至纯出池 ✓。

**三层架构（主人确认）**：
① 盘前 universe = 主板+D-1未涨停+主人版低位四条件（装低位妖股，MA20 下门日照产）；
② 盘前 txt = 低位池按板块 20 日动量降序前 100（「低位+题材」核心路径——低位组
唯一区分因子 51.3% vs 39.9%）；
③ 自动买入层 = 深跌排除+白名单+MA20 门不变（低位口径自动回测 -4.9%/PF 0.94 已否决，
安全垫换弹性——低位池定位人工观察清单，两层分离）。

改动：`_is_owner_low_position`（leader_minute_backtest.py）+
premarket_prelude_service 重构（universe 换低位四条件、板块动量排序、形态降级为展示、
limit=0 全量快照+API 层截断）+ ruleFlow 第⑨节点改「盘前低位首板观察池」+
测试（锚点/至纯 V 形/底部震荡语义守护 21 个新增）。

## 风险与边界

- B 型小样本（1070），结论带 n/CI；形态阈值 ±3% 为主人先验，敏感性只做预声明 2/3/4% 三档
- in-sample 窗口含一次完整涨跌周期；量能方向条件默认不进硬滤（月度一致性门槛 0.7）
- txt 链路走 authFetch（非 {success,data} 包装）；快照 job 未跑时 API 实时算兜底（慢但可用）
