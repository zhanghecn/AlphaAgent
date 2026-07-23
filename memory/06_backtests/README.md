# Research Evidence Index

## Current State

### 正式打板基线

- 唯一正式合同为 `limit-up-history-v15`、`limit-up-live-v15`、
  `limit-up-scheduled-v9` 和 `limit-up-cash-v5`。首板、二进三、两仓现金占用、
  正式费用和 D+1 官方收盘退出均保持不变。
- 冻结的 802 日正式组合基线有 170 个信号、99 笔两仓成交：胜率 `69.6970%`、复利
  `+171.7614%`、最大回撤 `-8.3083%`、利润因子 `2.8454`。
- 本地运行库已自然推进到 `2026-07-22` 的 804 个可靠交易日；冻结报告、模型指纹和
  44/15/30 切分仍使用原 802 日输入，不随运行数据增长重调。
- 全量推荐独立槽位的冻结口径为 `170信号/166闭合/62.0482%/+1.3025%`；按当前代码和
  运行库滚动重算至 `2026-07-22` 为
  `198信号/194闭合/61.8557%/+1.3332%/+425.7392%复利/-13.7650%回撤`。两者都不是
  两仓现金账户，冻结与滚动数字必须分开引用。
- 正式首板基线使用当天实际触板事件形成候选，适合作为触板执行基线和标签来源，但不是
  因果的板前候选生成器。

### 板前决策合同

- 集合顺序固定为：
  `raw_capture_pool -> eligible_first_board_pool -> quality_pool -> action_pool -> filled_pool`。
  股票必须先通过正式路径同源的点时首板质量门，然后 `change_pct >= 3` 才启动观察。
- `>=3%` 不是全市场候选规则、训练母池或买点。普通 3% 股票和质量门失败股票不得进入
  个股模型、页面推荐或组合。
- prior-only 的 D+1 预期收益、D+1 胜率、触板/封板基因和封板后 D+1 证据继续负责交易
  质量；动态层只估计未来三分钟正式触板概率和当日最终正式触板概率。
- 历史回放和实时评分已经共用质量评估、特征投影、模型合同、状态机和稳定排序；后来
  触板/封板和 D+1 结果只在特征冻结后连接。实时只允许行情适配器不同，并公开一个
  `preboard_candidates`。
- 正式 v15 扫板买点和新板前观察是两条独立输出：严格板前股票触板后退出
  `preboard_candidates`，但合格的 `near_limit/sealed/resealed` 仍可保留正式涨停价排队
  买点，二进三和两仓不受影响。

### 冻结结论

- 冻结研究使用 44 fit、15 calibration、30 validation，1,044 个完整一分钟/逐笔高质量
  股票日，共 73,527 条点时质量行。候选索引是标签无关上界，不能称为全市场 3% 股票。
- 两个概率头均为 `ready`：三分钟/最终触板 Brier skill `+0.1409/+0.2252`、PR-AUC
  `0.3290/0.4321`、机会 Top20% lift `4.39/3.39`。
- 最终状态为 `historical_rejected`，执行模式为 `research_only`，正式激活为
  `not_eligible`，`formal_strategy_changed=false`。概率能排序不等于继承触板基线约 70%
  的 D+1 胜率。
- validation A 正式首板账户为 22 笔、胜率 `68.18%`、复利 `+28.90%`、回撤
  `-4.66%`、PF `3.7170`。
- validation C 严格板前首板账户为 25 笔、胜率 `52.00%`、复利 `+14.95%`、回撤
  `-9.17%`、PF `1.5270`；37 个动作最终触板率 `43.24%`、未触板误报率 `56.76%`。
  严格联合账户为 26 笔、胜率 `50.00%`、复利 `+18.74%`、回撤 `-9.12%`。
- 市场、概念/行业、个股资金、当前换手和新鲜度因历史点时覆盖不足统一为
  `diagnostic/non-blocking`；只有共享风险、窗口、完整分钟和严格板前价格可以阻断。
- 冻结数据指纹：
  `sha256:56a880540b1005a39a775f68181c02fcf3a9cf05823e531ba37284b51e561baf`。
  候选索引指纹：
  `sha256:73bce5b983cb694c56786a7f138aa758bde27a61967b64aa0e8012975cd5863e`。
  冻结模型指纹：
  `sha256:b1d4ca83ca4dad25e1e74cda21c5b01c4f40d6e62ed9da62582d6eb8c651b71a`。
- 最新回放耗时 `1811.478s`；当前 A/C Markdown SHA256 为
  `603367f4446df5f33ce8c8c84e84eb416931b12a4ad5307d1ccaee76e860d784`。原始 JSON
  体积大且仍含已删除的旧账户字段，不作为当前证据保留；需要时由冻结命令重新生成。

### 最近交易日实时时序

- 2026-07-22 正式回测首板为 0，但旧实时雷达原始 `buy_now` 有 13 只，证明旧原始实时
  动作不是正式触板回测质量。全量 `actionable_recommendations` 现已统一执行首板
  `>=5` 个 D+1 样本和 `>=30%` 同股联合率，不受两仓数量限制；二进三不变。
- 2026-07-23 的正式首板漏斗为 `9 eligible -> 8 位于窗口 -> 7 通过盈利门`，7 只最终
  全部触板并封住，D+1 尚未闭合。修复前内部 v15 对 5/7 在触板前出现，领先中位数
  `7.11` 分钟；公开快照实际只有金煤科技具备分钟级准备时间，盛新锂能只剩约 8 秒。
- 当日 10:00..10:44 有 499 条 live trace、249 个 radar frame，却没有公开 snapshot；
  第一条公开快照为 10:45:39。旧正式快照被同步研究评分挡在落库之后，现已改为先保存
  v15，再做概率增强。
- 当日午后第一帧直到 13:20:38，导致 13:04 触板的联环药业无实时输入。盘中主扫描现已
  移除逐股分钟和 TDX 逐笔网络回填，只使用完成分钟缓冲；缺失时保持观察。部署后的真实
  最大帧间隔仍需由后续前向账本确认。
- 2026-07-20 起共享概率 feature row 为 0，最近两日概率 TopK 和误报率不可计算。旧 v15
  动能轨迹不得冒充 `touch_probability_3m / eventual_touch_probability`。
- 正式 v15 扫板买点保留 `near_limit/sealed/resealed`；封板/回封时的
  `buy_now` 表示可尝试涨停价排队。只有新 `preboard_candidates` 要求严格板前，
  触板后从板前观察列表退出，不得过滤正式扫板列表。活动交易时段实时快照
  轮询为 10 秒，较大轨迹仍为 60 秒。

### 当前运行状态和未来研究

- 板前决策服务加载唯一当前模型并返回概率观察；当前是
  `ready / historical_rejected / research_only / not_eligible`，动作表保持 0，
  `formal_strategy_changed=false`。旧板前模型不能被当前 loader 装载。
- 正式 v15 的 `actionable_recommendations` 是不受两仓容量约束的旧触发列表；`portfolio`
  才是两仓现金回测的实时对应列表。当前全量首板也执行正式盈利质量门；板前研究未晋级前
  不改这两个正式列表，也不能把全量推荐约 62% 的质量指标误称为约 70% 的两仓账户胜率。
- 2026-07-23 源码收口验收为打板后端 `794 passed`、data-sync `155 passed`、前端
  提交态 `120 passed`；生产构建、compileall、开发/部署 Compose 配置和差异检查均通过。
  独立板前 worker 已从代码、Compose 和运行容器删除，21:30 统一任务负责冻结与结算。
- 旧公共 `/api/limit-up/radar-validation` 及其服务已删除，不参与当前共享模型可用性、
  动作或正式晋级判断。
- 只有新的独立预注册研究具备足够的点时市场、板块、个股资金和新鲜度历史，先通过冻结
  历史账户门、再通过独立前向账户门，才允许整体替换旧首板触发和排序。
- 不在已查看 validation 上继续调阈值，不恢复固定涨幅买点或已删除的兼容分支。

### Evidence

- 最新报告：`limit_up_preboard_decision_validation_20260723.md`。原始 JSON 按需由冻结
  回放命令重建，不进入仓库。
- 最近交易日买点对照：`limit_up_live_vs_backtest_entry_audit_20260723.md`。
- 需求合同：`requirements/alphaagent_limit_up_preboard_decision.md`。

## Low-suction Status

- 低吸继续使用独立的 `low-suction-swing-paper-v1` 前向纸面合同、候选/持仓/交割单表
  和产品 Tab；不连接券商自动下单，也不与打板共享候选或绩效。
- 严格历史概念成员覆盖仍不足。历史回放只能标记为生存偏差代理，不能解锁纸面资格
  或正式收益声明。
- 历史信号日收盘确认与同收盘成交不是已证明的可执行价格；自然前向结果必须独立累计，
  禁止回填历史候选。
- 当前产品和账户决定集中在 `memory/09_decisions/decisions.md`，数据覆盖集中在
  `memory/03_data/data_flow.md`。详细实验结论只保留在各自证据文件，不再复制到本索引。

### Evidence

- 研究边界：`requirements/alphaagent_low_suction_research_reset_design.md`。
- 证据目录：本目录下 `low_suction_*.md`；每份报告自行声明数据口径、状态和是否可执行。

## Verification

```bash
uv run --group server pytest -q tests/alphaagent/services/low_suction
npm --prefix frontend test -- --run
npm --prefix frontend run build
```
