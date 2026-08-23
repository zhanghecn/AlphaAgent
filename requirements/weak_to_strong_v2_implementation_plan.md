# 趋势弱转强产品实施计划

Goal: 把弱转强 v2 研究产品化为短线研究第三条产品线(实时推荐/回测/历史交割单/
规则说明 + A1/A2/B 三串同花顺条件复制),策略口径 = 定稿 v2,一字不改。

设计文档:`requirements/weak_to_strong_v2_design.md`(规则/口径/验收标准以此为准)
策略定稿:`量化因子研究/低吸研究/趋势低吸研究-弱转强v2.md`
复跑基准:研究 prep(会话内 /tmp/erban_prep.py,Phase 0 第一件事固化为仓库内脚本)

提交规则:用户明确要求才 git commit/push;直接提交 master,不建 feature 分支;
前端全链路只走 Docker Compose(不起 5173);发布走 ghcr 镜像(v* tag)。

## 关键既有事实(执行者必读)

- 潜龙模板(同构复用,2026-08-23 已验收):服务 `alphaagent/server/services/qianlong/`
  (contracts.py 规则事实源 / pool.py:44 compute_pool / live_scan.py:46 run_live_scan_tick /
  eod_finalize.py:28 run_eod_finalize / backtest.py:32 run_backtest / repository.py /
  service.py API 门面+重建锁);API `alphaagent/server/api/qianlong.py` 七端点;
  表 `alphaagent/server/db/schema.py:1763-1879`(五件套);
  前端 `frontend/src/pages/QianlongPage.tsx` 四页签 + `frontend/src/features/qianlong/`
- 复制按钮:`frontend/src/features/qianlong/CopyThsConditionsButton.tsx`(clipboard + 降级 + toast,
  纯展示组件直接搬);条件串后端 contracts.py 下发,`/rules` 单一事实源
- 短线研究挂载:`frontend/src/pages/ShortTermResearchPage.tsx`(`?research=` 两 tab,
  新增第三 tab `weak-to-strong`)
- 连板状态:`stock_limit_up_daily`(schema.py:1736,is_limit_up/limit_up_count/touched_limit,
  索引 (trade_date)/(vt_symbol, trade_date));判定器 `services/lianban/detector.py:77 classify_limit_up`
- 盘中现货:腾讯现货缓存(潜龙 live_scan 同款,MIN_SPOT_FRESH_SYMBOLS=3000 新鲜度门槛)
- 调度新增 job 四处同步:`DEFAULT_JOBS` / `JOB_CADENCES` / `JOB_RUNNERS` /
  `DEFAULT_BATCH_SCHEDULES`(`data_sync.py`,低吸 :642/:519/:2490/:631 附近,
  潜龙 :285-300/:545/:2549/:697-767);`create_all` 不补索引,需显式 Index —— 既往教训
- 版本纪律:规则/口径变更必升 `W2S_RULES_VERSION`,物化带版本,worker 启动自检补漂移
  (参照 SCORE/BACKTEST_VERSION 事故)

## Phase 0 口径对账(1 天)

1. 把研究 prep(事件池构建:连板序列/距末日天数/下影/振幅/量比/底座/大盘涨停数/前向 15 日)
   固化为 `量化因子研究/低吸研究/scripts/w2s_replay.py`(docker exec 可跑,
   输出三组池名单 + 锚点数字),作为对账基准
2. A2 上影线口径确认:研究"上影线<2%"实为 (最高−收盘)/昨收(fade,复跑 177/+1.80/63
   ≈ 定稿 208/+1.87/63;标准上影线口径 549/+1.52/60 不符)——设计文档 §3 已按此写,
   本步复核无误后锁死
3. B 组样本差复核(定稿 168 vs 复跑 145):确认组划分定义(前段高度/距末日起算)后
   出修正锚点,回写设计文档 §2 锚点表(潜龙锚点修正先例)
4. 同花顺条件串 ×3 问财实测:建动态板块数对账;A2 串"上影线"字段与产品池口径
   (fade)在阴线日的出入量化记录;不通字段换同义表达,最终串回写设计文档 §4.5

## Phase 1 后端基建(2 天)

1. `schema.py` 新表 5 张:`w2s_pool_entries`(PK trade_date+vt_symbol+group_key)/
   `w2s_signals`(同 PK)/ `w2s_live_scan_runs` / `w2s_backtest_runs`(id=1 JSONB)/
   `w2s_backtest_rebuild_runs`(索引显式:trade_date、状态)
2. `services/weak_to_strong/contracts.py`:阈值常量、三组规则结构化、证伪清单、
   风险声明、同花顺条件串 ×3(THS_POOL_CONDITIONS_A1/A2/B + NOTE)、盘中执行要点、
   回测锚点(Phase 0 修正值)、`W2S_RULES_VERSION = "w2s-v2"`
3. `services/weak_to_strong/pool.py`:盘前池纯函数(输入日期,输出三组池+条件快照值):
   从 stock_daily_bars 算 T-1 特征(跌幅/上下影(fade 口径)/振幅/换手/量比 vol÷ma5/
   底座 ret20),从 stock_limit_up_daily 重放连板序列得 last_streak/gap_days/昨日大盘涨停数;
   组划分互斥(=2→A,≥4 且 gap≥3→B,=3→弃);无未来函数(全部 T-1 收盘)
4. `services/weak_to_strong/repository.py`:池整覆写/信号 upsert/扫描轨道/报告读写
5. `api/weak_to_strong.py` 七端点(设计文档 §6),注册 `api/router.py`;
   `/rules` 下发三串条件(验收 4 的数据源)
6. 池对账:随机 5 个交易日,产品池 vs `w2s_replay.py` 三组名单 100% 一致(验收 1)

## Phase 2 盘中扫描 + EOD 定版(1.5 天)

1. `services/weak_to_strong/live_scan.py`:每分钟扫池内现货(09:30~15:00 窗口,
   PG advisory lock 换新 key);A1 首次扫描定 gap_open,0~+4% 外 → skipped_gap;
   halted 池整日只跟踪不触发;A1/B 现价 ≥ 触发价(昨收×1.07)→ touched+entered
   (买价=触发价,无滑点);A2 现价 = 涨停价 → entered(买价=涨停价)
2. `services/weak_to_strong/eod_finalize.py`:定版今日信号(残留 watching/touched→
   no_trigger,sealed 从 stock_limit_up_daily 回填)+ 在持退出重放(T+1 起首个未涨停日
   收盘卖,next_close_fail/break_close/max_hold_close 三原因)+ 次日池计算落库;幂等可补跑
3. 调度三处注册:`w2s_live_scan`(`* 9-15 * * 1-5`)、EOD 链尾(eod_1900/2130)
   `w2s_eod_finalize`、`w2s_backtest_2250`;健康审计心跳阈值同步加

## Phase 3 回测引擎产品化(1.5 天)

1. `services/weak_to_strong/backtest.py`:日线全量回放(2023-04 起):
   A1/B 触发 = 最高 ≥ 昨收×1.07 且最低 ≤ 触发价(可达才成立);A1 竞价过滤用当日开盘价;
   停手日整组跳过;A2 = 收盘封板才买(买价=涨停价);卖出 = T+1 起首个未涨停日收盘,
   T+15 兜底;|隔夜缺口|>11% 伪触发剔除
2. 物化报告:分组汇总(n/封板率/D+1/胜率/连板率/板留断走)+ A1 竞价对照 +
   分年表(B 组 2023 负常驻提示)+ 月度表 + 逐笔等权净值 + 锚点对照(超容差标黄数据)
   + ledger_days(最近 60 交易日逐笔);写 `w2s_backtest_runs`(id=1)+ rules_version
3. `POST /backtest/rebuild` 后台线程 + 409 去重 + `/backtest/status` 阶段进度
4. 对账:三组 = 设计文档 §2 修正锚点(验收 2);五案例行为抽查(验收 3)
5. 调度批 `w2s_backtest_2250` 每日物化

## Phase 4 前端四页签 + 第三 tab(2.5 天)

1. `frontend/src/api/weakToStrong.ts` 客户端与 TS 契约(group_key/状态联合类型)
2. `frontend/src/features/weakToStrong/`:LiveView / BacktestView / LedgerView /
   GuideView;复制按钮搬 CopyThsConditionsButton(改三串组选择:A1/A2/B 各一按钮或下拉)
3. `frontend/src/pages/WeakToStrongPage.tsx` 四页签容器(照 QianlongPage:26-31);
   `ShortTermResearchPage` 加第三 tab「趋势弱转强」`?research=weak-to-strong`
4. live 页:状态条(三组计数/停手红条/最近扫描)+ 组徽章主表 + skipped/halted 灰显;
   30s 轮询,历史日期停止轮询
5. guide 页:静态文案(基本条件/A1/A2/B/买入/卖出 + 数据支撑摘要 + 证伪清单 +
   风险声明 + 五案例锚点 + 与低吸「B 涨停弱转强 P1.5」的区分互链),
   配 `w2sGuideContent.spec.ts` 防漂移断言(低吸 spec 模式)
6. 低吸 guide 页加一行交叉指引(“打板反包打法见趋势弱转强”)
7. 设计系统 v3.1 终端蓝,零动画铁律,数字 JetBrains Mono

## Phase 5 联调验收上线(1 天)

1. 验收清单 1~7 全跑(设计文档 §8),含五案例抽查与状态机全路径样本
2. `docker compose up --build` 全链路;调度日志确认三批次注册与首跑成功
3. 线上发布:ghcr 镜像纪律,发版后 reconcile 日志确认物化无漂移
4. 更新 `requirements/README.md` Current decision(短线产品两条 → 三条产品线)

## 里程碑与工作量

| 阶段 | 内容 | 工作量 | 完成标志 |
|---|---|---|---|
| P0 | 复跑脚本固化 + 口径对账 + 问财实测 | 1d | 修正锚点回写、条件串定稿 |
| P1 | 后端基建(表/契约/池/仓储/API) | 2d | 七端点通,池 5 日全对 |
| P2 | 盘中扫描 + EOD 定版 + 调度 | 1.5d | 两链跑通,信号状态机推进 |
| P3 | 回测产品化 + 锚点门禁 | 1.5d | 回测对账达标,重建可用 |
| P4 | 前端四页签 + 第三 tab + 复制 | 2.5d | 四页签齐,三串复制可用 |
| P5 | 验收上线 | 1d | 验收 1~7 全过,线上发布 |

合计约 9.5 个工作日。P0→P1 有依赖;P2 与 P3 可并行;P4 的 guide 文案可随时先写。
