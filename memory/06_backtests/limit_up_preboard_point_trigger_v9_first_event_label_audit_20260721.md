# 首板点触发 v9 首次事件标签审计（2026-07-21）

## 结论

点触发标签必须把同一股票交易日第一次正式首板 `buy_now` 视为唯一事件。正式快照在股票
触板后会连续多帧保持 `buy_now`；这些是同一状态的重复观察，不是新的触板事件。旧语义
把重复帧当作新事件，显著高估了 60 秒正例数量和可达事件数。

修复后，2026-07-21 排除日的真实保存数据仍证明了提前观察的物理可行性：40 个正式买入
窗口内首次首板事件中，13 个能由当前静态候选池和连续 60 秒标签严格到达，正例锚点领先
正式事件的中位数为 `31.5565s`。这不是模型精度、胜率或收益证据；该日已经不可变冻结为
`incomplete`，不得进入 fit、calibration 或 validation。

## 缺陷与修复

- 原始数据有 `7,026` 条首板 `buy_now` 观察，但只有 `42` 个不同首板股票日，重复倍数为
  `167.2857x`。其中第一次事件落在正式买入窗口内的股票日为 `40` 个。
- `attach_point_trigger_labels()` 现在先按 `(trade_date, vt_symbol)` 只保留第一次正式首板
  `buy_now`，再在 `(t,t+60s]` 中寻找候选池内最早身份。后续保持 `buy_now` 的帧不能再
  产生正例事件。
- 市场事件时钟也按每只股票的首次事件计数。同一帧两只股票首次触板应计为两个事件；同股
  后续重复帧不得重复计数。
- 两条反例测试分别锁定“同帧不同股票各计一次”和“同股重复 `buy_now` 不制造 60 秒
  正例”。

实现与测试：

- `alphaagent/server/services/limit_up/preboard_point_trigger_dataset.py`
- `tests/alphaagent/test_limit_up_preboard_point_trigger_dataset.py`
- `test_market_event_clock_counts_each_stock_once_at_a_shared_frame`
- `test_sixty_second_labels_ignore_repeated_buy_now_after_first_stock_event`

## 只读重放证据

重放从运行库读取 2026-07-21 的 `limit_up_radar_frames` 和
`limit_up_radar_observations`，在 `alphaagent-research` 的固定 `0.10 CPU`、单数据库连接、
关闭 PostgreSQL 查询并行的资源边界内执行。只调用 `load_frames()`、
`load_observations()`、`build_point_trigger_rows()` 和标签函数；没有调用冻结、模型、动作或
归档写入接口。

| 项目 | 数值 |
|---|---:|
| 原始帧 | 970 |
| 原始观察 | 277,886 |
| 因果候选行 | 32,962 |
| 候选股票 | 109 |
| 候选帧 | 680 |
| 首板 `buy_now` 原始观察 | 7,026 |
| 不同首次首板股票日 | 42 |
| 买入窗口内首次首板事件 | 40 |

标签修复前后使用同一批因果候选行：

| 标签语义 | 已知帧 | 正例帧 | 正例率 | 可达事件 |
|---|---:|---:|---:|---:|
| 旧：每个重复 `buy_now` 都可成为事件 | 602 | 170 | 28.2392% | 65 个伪重复事件 |
| 新：每股票日只认第一次正式事件 | 601 | 53 | 8.8186% | 13/40 个首次事件 |

修复后 53 个正例帧的领先时间 P50/P90 为 `31.5565/52.0809s`；每个可达首次事件对应的
正例锚点数 P50/P90 为 `4/5`。这说明 10 秒级轨迹通常能在正式事件前留下多个观察锚点，
但真实正例率仅约 8.8%，同刻身份排序仍是主要难题。

## 分段诊断

| 时段 | 已知帧 | 正例帧 | 正例率 | 可达首次事件 | 领先 P50/P90 |
|---|---:|---:|---:|---:|---:|
| 10:00..11:30 | 159 | 0 | 0% | 0 | - |
| 13:10..14:10 稳定段 | 330 | 26 | 7.8788% | 7 | 31.8729/54.1673s |

上午本身已经因扫描节拍、概念覆盖和运行指纹失败，不能用“上午零正例”调整交易窗口、特征
或阈值。下午稳定段只证明采集和标签链路能产生真实正例，也不能替代完整日或估计模型表现。

## 对前向合同的影响

- 保留 `>=3%` 仅作为观察分母；本次修复不增加买点或放宽静态母池。
- 40/15/60 日期、模型参数、阈值集合、两仓限制和 `reliability-v8` 门槛均不改变。
- 2026-07-21 scope、feature/model/action 表和最终归档均不回填。
- 下一合格交易日开始，训练标签和 20/60/180 秒市场事件时钟统一使用首次事件语义。
- 当前状态仍为 `collecting_fit`，真实进度 `0/40 + 0/15 + 0/60`；不得据此声称方案可靠。

## 验证

```bash
uv run --group server pytest -q \
  tests/alphaagent/test_limit_up_preboard_point_trigger_dataset.py
uv run --group server pytest -q \
  tests/alphaagent/test_limit_up_preboard_point_trigger_*.py \
  tests/alphaagent/test_limit_up_radar_observation_repository.py
uv run --group server pytest -q \
  tests/alphaagent/test_limit_up*.py \
  tests/alphaagent/test_data_sync*.py
```

当前结果依次为 `40 passed`、`184 passed`、`1207 passed`（最后一组含 1 条既有
Starlette 弃用警告）。定向 Ruff、compileall 和 `git diff --check` 同时通过。
