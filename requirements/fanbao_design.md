# 断板反包打板产品设计（fbb）

短线研究第 5 页签 `/short-term?research=fanbao`。研究定稿与口径全档见
`量化因子研究/反包/`（需求 / 规则 / 研究方向三文档 + 汇总 + 好差票验证月度档）；
本文件只记产品架构，当前版本 `fbb-v2.1`。

## 一、策略一句话

前波连板（2板/4板/5+板）断板 1~3 天后又涨停的票，反包日触涨停价按涨停价买。
出手五方案点：S1 低开急杀（2板）、S2 高开洗透（4板断1）、S3 高位扛住（5+板断1）；
O1/O2 观察级只看不买。卖出单一纪律：反包日炸板当天收盘走，封住拿到断板日
（15 交易日兜底）。无首刻窗（与高位接力最大差异：触板即买）。

## 二、后端服务包（镜像 high_relay 结构）

`alphaagent/server/services/fanbao/`：

| 文件 | 职责 |
|---|---|
| contracts.py | 规则契约唯一事实源：版本、五点条件（tag_point）、死格（dead_cell_reason）、顶格开警示（is_high_var_open）、锚点与案例门禁、/rules 文案 |
| pool.py | T-1 盘前池：derive_daily（含 notlim_run/notlim_prev 断板计数）→ break_fields（断板期快照+末日开盘方式）→ tag_point → compute_pool |
| live_scan.py | 盘中每分钟：触板即 entered（无首刻窗）、一字开 sealed_watch（T字打开=排板成交）、advisory lock 726110 |
| eod_finalize.py | 盘后：首触回填（w2s_touch_times 共用）→ 残留定版 → 退出推进 + 坏票定版（bad_ticket）→ 次日池 |
| backtest.py | 全量回放 2023-01 起：summary/matrix18/参考行/阴线坑深切分/ledger_days，锚点自校对 |
| repository.py / service.py | fbb_ 表读写 / API 门面（rebuild 409 去重+版本门禁+run_backtest_sync） |

## 三、数据表（fbb_ 前缀五张）

- `fbb_pool_entries`：池（断板期全字段：gap/n_board/group6/yin_yang/break_*/last_entity/last_open_pct）
- `fbb_signals`：信号状态机 8 态 + bad_ticket
- `fbb_live_scan_runs` / `fbb_backtest_runs`(id=1 JSONB) / `fbb_backtest_rebuild_runs`

## 四、调度（data_sync.py 四档 + worker reconcile）

- 盘中扫描 `* 9-15 * * 1-5`（fbb_live_scan）
- eod 定版挂 eod_1900 与 eod_finalize_2130 两批
- 回测重算 `20 23 * * 1-5`（fbb_backtest_2320，与 22:30 低吸/22:50 w2s/23:05 hpr 错峰）
- worker 启动 `_start_fbb_report_reconcile`（版本漂移自动重建）

## 五、验收锚点（fbb-v2.1，回测对账基准）

| 点 | n | 持有 | 胜率 | 分年 |
|---|---|---|---|---|
| S1 低开急杀 | 76 | +3.85 | 58% | +9.3/+1.1/+3.2/+6.3 四年全正 |
| S2 高开洗透 | 34 | +4.12 | 65% | +1.5/+5.5/+3.8/+4.3 四年全正 |
| S3 高位扛住 | 30 | +7.02 | 67% | 24~26 = +13.2/+7.8/+1.4 |
| S级合计 | 140 | +4.60 | 62% | — |

上线验证：方案点锚点 7/7（n_diff=0）、矩阵抽 3 格、案例门禁 10/10
（含跨境通/新能泰山 out 案例验证 v2.1 收紧逻辑）。

## 六、前端

`frontend/src/`：api/fanbao.ts（契约）、pages/FanbaoPage.tsx（四页签容器，
30s 轮询）、features/fanbao/Fbb{Live,Backtest,Ledger,Guide}View.tsx。
Live/交割单带「末开%」列与顶格开 ⚠ 警示（>7% 减半仓）；交割单按
坏票/好票两分组展示（好差票验证月度文件的产品化等价）；规则说明为
直白文案（后端契约驱动，前端不维护副本）。
