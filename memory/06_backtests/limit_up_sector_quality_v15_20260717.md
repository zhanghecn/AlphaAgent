# Limit-Up Live V15 Sector Quality Final Replay

## Final Result

`limit-up-live-v15` 修复了 v14 收益下降的直接原因：概念 `observe/warming` 不再能以
概念单路形成正式买点；概念单路必须实时达到 `launch`。盘中行业扩散路径继续独立
有效，因此不会重新阻断深南电A这类 D-1 热度偏低、但当日行业真实共振的股票。

同一批 2026-07-15..17 的 643 个点时保存快照、同一买入窗口、同一 D+1 收盘退出和
同一费用口径重放结果：

| 规则 | 7月15日闭合信号 | 胜率 | 平均净收益 | 当日等权收益 |
| --- | ---: | ---: | ---: | ---: |
| v14 行业或非退潮概念核心 | 15 | 46.6667% | +1.0774% | +1.0774% |
| v15 行业或概念启动 | 11 | 63.6364% | +2.9050% | +2.9050% |

v15 两仓按信号真实到达顺序成交最早两只，不事后选择：2 笔、2 胜，胜率 100%，
账户收益 `+5.7892%`，最大回撤 `-0.0309%`，总费用 116.2794 元。

## Cause

v14 把“新鲜完整、至少 2 只涨超 5%、个股为 Top3、但概念尚未 launch”的概念核心
也当成正式路径。唯一闭合日中，v15 删除的 4 只始终未启动概念单路信号全部亏损，
平均净收益约 `-4.11%`。v14 新增覆盖因此提高了信号数量，却直接拉低胜率和收益。

盘中行业独立路径的湖南发展为盈利信号，不能与上述弱概念单路一起删除。因此最终规则
不是退回 D-1 热度门，而是保留行业实时路径、只收紧概念实时路径。

## V15 Contract

- Entry windows: `10:00-11:30`、`13:00-14:30`
- Exit: D+1 官方日线 `close_price`
- Industry route: 盘中行业触板扩散达标，当日行业资金已就绪且无严重净流出
- Concept route: 数据新鲜完整、`launch`、至少 2 只涨超 5%、个股为概念 Top3
- D-1 heat: 只诊断和排序，不参与买点阻断
- First-board history: 历史胜率、联合率和成熟同路径风险只排序，不否决正式推荐
- Portfolio: 两仓组合仍可使用联合率做组合选择；二进三合同不变
- Formal source: 保存帧 `recommendations.actionable_recommendations`
- Point-in-time selection: 同股同日只取第一次进入正式列表的保存帧
- Costs: 双边 10 bp 滑点、万三佣金、最低 5 元、万 0.1 过户、卖出万五印花税

三个保存日的去重首板信号数由 v14 的 `15/20/10` 收紧为 v15 的 `11/9/9`。7月16日
和 7月17日尚未具备对应 D+1 官方收盘，本报告不使用盘中价替代。

## Live Acceptance

2026-07-17 14:19:23 首个真实 v15 保存帧形成 3 个正式推荐，14:24:45 再新增宁波能源：

| 股票 | 路径 | 历史证据角色 | 前向订单 |
| --- | --- | --- | --- |
| 华银电力 `600744.SSE` | `realtime_industry` | `ranking_only` | 已记录 |
| 深南电A `000037.SZSE` | `realtime_industry` | `ranking_only` | 已记录 |
| 赣能股份 `000899.SZSE` | `realtime_industry` | `ranking_only` | 已记录 |
| 宁波能源 `600982.SSE` | `realtime_industry` | `ranking_only` | 已记录 |

截至 14:26，`limit-up-forward-validation-v2` 产生同样 4 笔订单，股票和各自首次时间
逐项一致；当前等待 D+1 收盘闭合。

## No-Lookahead Audit

短线研究页的“规则说明”由只读接口 `GET /api/limit-up/strategy-guide` 提供，统一展示
v15 选取顺序、字段时点和本报告的 643 帧数据指纹。接口不触发行情刷新或回测重算。
页面同时单列 800 日历史候选代理，并明确标记为非 v15 实盘等价证据；两者是一套正式
规则的不同证据层，不是“推荐 A、执行 B”，胜率也不得混算。

- 盘中实时字段和信号日前已知字段允许参与选股。
- `result_date < signal_date` 是历史胜率样本的硬截止条件。
- D 日最终封板、D+1 官方收盘、净收益和后续快照均标记为事后字段，禁止参与选股。
- 同股同日按 `captured_at` 只取第一次规则通过的保存快照；后续状态不能改写首次买点。
- “无未来函数”只描述选取时点；没有 Tick/L2 排队成交回报时，扫板成交仍是价格代理。

## Verification

- Staged-tree backend limit-up regression: 521 passed
- Staged-tree frontend: 74 passed
- Current working-tree backend/frontend: 529 / 75 passed
- TypeScript/Vite production build: passed
- Python compileall: passed
- `git diff --check`: passed
- Playwright desktop/mobile (`1280x720`, `390x844`): passed; console errors 0
- Current local API/Web containers: healthy
