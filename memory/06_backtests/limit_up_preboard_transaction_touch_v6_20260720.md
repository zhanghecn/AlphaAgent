# 首板逐笔触板时序 v6 研究

## Current state

- 状态：`ready_historical_rejected`；结论：`historical_rejected_no_live_promotion`。
- 研究版本：`limit-up-preboard-transaction-touch-v6`；正式策略修改：`False`。
- 逐笔覆盖：股票日 962/962；分钟前缀 22804/22821。

## Deterministic rerun

- 最终代码连续两次完整复跑，除 `performance` 耗时外整份 JSON 逐字段完全一致；
  日期切分、数据、模型、19 个阈值点、动作、oracle、账户、遗漏归因和验收均一致。
- v6 动作政策/模型/阈值/动作/oracle/验证账户指纹分别为
  `sha256:9523eb1e927e870b0f121d530b866506c7686662e0ab91a5b423b7c1b09ae30a`、
  `sha256:8b2ad23af9ec685c538ce812eb2a0775cde58c160167f2c1452e0c7663461013`、
  `sha256:94a249282a6a592e9fa5253957c26b9ecb3e174d11b6dec23ad16817e376ac08`、
  `sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`、
  `sha256:80b82712d39b7c71cd4dfa8ed0bd8936a62547a5968b550d37ba638df9a130f2`、
  `sha256:718078f404f154fcbaf63ba24ca516f16834e9761a29f8f5059f616a139f07bf`。

## Timing calibration

- 状态：`calibration_precision_gate_failed`；冻结阈值：`None`；动作确认：1个完整分钟。
- 满足最少样本数的最佳校准点：阈值 0.55，6/13，触板精度 46.15%。
- 验证段 v6 动作 0；三分钟触板精度 -；阈值失败时组合账户只含未改动二进三，不代表 v6 提前买入收益。

## Same-account validation

| 方案 | 信号 | 原账户身份精度 | 原账户召回 | 成交 | 胜率 | 复利 | 回撤 | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| v3分钟模型 | 34 | 30.43% | 33.33% | 25 | 44.00% | -16.84% | -26.25% | 0.6451 |
| v6触板时序模型 | 0 | - | 0.00% | 3 | 100.00% | +9.27% | -0.67% | - |

## Validation blocks

| 块 | 日期 | 行动 | 成交 | 胜率 | 复利 | 回撤 |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 2026-06-04..2026-06-11 | 0 | 1 | 100.00% | +4.02% | -0.67% |
| 2 | 2026-06-12..2026-06-22 | 0 | 0 | - | +0.00% | +0.00% |
| 3 | 2026-06-23..2026-06-30 | 0 | 2 | 100.00% | +5.09% | -0.02% |
| 4 | 2026-07-01..2026-07-08 | 0 | 0 | - | +0.00% | +0.00% |
| 5 | 2026-07-09..2026-07-16 | 0 | 0 | - | +0.00% | +0.00% |

## Incremental attribution

- `v3_false_momentum_removed_by_v6`：26 个股票日。
- `v3_original_account_identity_retained`：0 个股票日。
- `v3_original_account_identity_killed_by_v6`：8 个股票日。
- `v6_new_original_account_identity`：0 个股票日。
- `v6_new_false_positive`：0 个股票日。

## Causal no-action attribution

- 全样本 17 个分钟、14 个股票日；验证段 7 个分钟、6 个股票日。
- 验证段与正式候选身份交集 1；与原两仓实际成交身份交集 1。

## Reachable oracle ceiling

- 仅作可达上界，不进入模型、阈值或验收。
- 原账户 21 个股票日；3分钟可达 16；oracle账户匹配 16。
- 可达召回：76.19%。
- Oracle账户仅作上界：18 笔，胜率 77.78%，复利 +42.37%，回撤 -2.45%。

## Interpretation

- 逐笔覆盖不是失败原因；完整三态覆盖为 100%，可评分覆盖 99.9255%，数据缺失为 0。
- 分钟级合同存在理论可达性：oracle 能覆盖并匹配原账户 16/21 个首板身份；但它读取
  未来原账户身份，只证明数据/买点上界，绝不是模型成绩。
- 当前 29 特征 Logistic 的辨识能力不足：满足至少 10 个校准选择时，最佳只有
  `6/13=46.15%` 三分钟触板精度，远低于冻结的 70% 门，因此没有合法动作阈值。
- 当前未研究清楚的是新的市场/板块状态能否提高横截面辨识，以及缺少秒级/L2 后
  5 个原账户身份如何提前覆盖；不得在已查看 30 日上继续调阈值回答这两个问题。

## Decision

- 历史门禁：`FAIL`。
- `baseline_parity`：通过。
- `both_models_ready`：通过。
- `calibration_threshold_ready`：未通过。
- `minimum_30_validation_actions`：未通过。
- `minimum_70pct_formal_precision`：未通过。
- `minimum_70pct_original_account_identity_precision`：未通过。
- `minimum_30pct_reachable_recall`：未通过。
- `positive_normal_account_return`：通过。
- `positive_double_cost_account_return`：通过。
- `maximum_drawdown_no_worse_than_10pct`：通过。
- `d1_win_rate_within_2pct_of_touch_baseline`：通过。
- `minimum_3_of_5_positive_validation_blocks`：未通过。
- `v3_reference_parity`：通过。
- `transaction_scope_coverage_100pct`：通过。
- `transaction_disposition_coverage_100pct`：通过。
- `transaction_data_missing_zero`：通过。
- `minimum_95pct_scoreable_prefixes`：通过。
- `minimum_1_2_normal_account_profit_factor`：未通过。

## Forward validation

- 状态：`not_promoted_historical_rejected`；交易日 0，闭合行动 0。

## Limitations

- 后30日已经被此前研究查看，只能称扩展历史时间反证，不是新的锁定留出。
- TDX逐笔是成交记录，不包含委托队列、撤单和封单排队。
- buyorsell枚举缺少可信公开语义，方向特征只使用direction_0/1中性名称。
- 历史通过也只允许冻结前向影子；正式v9/v15保持不变。
- TDX当日逐笔API已确认可用，但当前实时推荐链路尚未接入；时间戳仅到分钟级，不能复现十秒级拉板或L2委托撤单。
