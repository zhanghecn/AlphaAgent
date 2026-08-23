# 潜龙首板产品实施计划

Goal: 把潜龙首板从无状态实时榜升级为四页签完整产品线(实时推荐/回测/历史交割单/
规则说明 + 同花顺条件复制),策略口径 = 条件定稿 v4,一字不改。

设计文档:`requirements/qianlong_first_board_design.md`(规则/口径/验收标准以此为准)
策略定稿:`量化因子研究/潜龙首板/潜龙首板条件定稿.md`
复跑脚本:`量化因子研究/潜龙首板/scripts/fb_*.py`(对账基准)

提交规则:用户明确要求才 git commit/push;直接提交 master,不建 feature 分支;
前端全链路只走 Docker Compose(不起 5173);发布走 ghcr 镜像(v* tag)。

## 关键既有事实(执行者必读)

- 低吸模板:页 `frontend/src/pages/LowSuctionPage.tsx`;视图 `frontend/src/features/lowSuction/`;
  API `alphaagent/server/api/low_suction.py`;服务 `alphaagent/server/services/low_suction/`;
  表 `alphaagent/server/db/schema.py:1414-1500`(快照/回测/重建轨道三件套)
- 现有首板榜:`frontend/src/pages/FirstBoardLeaderPage.tsx` +
  `alphaagent/server/api/first_board.py` + `services/first_board/live_service.py`
  (东财涨停池,limit_up_count==1,封单成比排序)——迁移为实时页辅助区
- 短线研究挂载:`frontend/src/pages/ShortTermResearchPage.tsx`(两顶层 tab)
- 盘中现货:`alphaagent/market/providers.py:81 _with_today_realtime_bar`;
  低吸分钟扫描 `daily_picks_service.py:183 refresh_live_recommendations` +
  `:1148 _merge_spot_bars`;调度批 `low_suction_live_scan`(`data_sync.py:642`)
- 调度新增 job 四处同步:`DEFAULT_JOBS` / `JOB_CADENCES`(`data_sync.py:519`)/
  `JOB_RUNNERS`(`:2490` 附近)/ `DEFAULT_BATCH_SCHEDULES`(`:631`)
- 复制按钮先例:`frontend/src/components/AppShell.tsx:52 copyText()` + useToast
- 涨停池落库先例:`limit_up_pool_snapshots`(schema.py:1668)
- 版本纪律:规则/口径变更必升 `QIANLONG_RULES_VERSION`,物化带版本,
  worker 启动自检补漂移(参照 SCORE/BACKTEST_VERSION 事故)

## Phase 0 口径对账(0.5 天)

1. 把池计算从 `scripts/fb_current_pool.py` 移植为
   `alphaagent/server/services/qianlong/pool.py` 纯函数(输入日期,输出池+8 条件快照值)
2. 对账:随机 5 个交易日,产品池 vs 研究脚本名单 100% 一致(验收 1)
3. 同花顺条件串问财实测(设计文档 §4.5):建动态板块数对账;不通字段换备选表达
   (「昨日收盘价大于20日均线」+「昨日20日乖离率0到12%」),最终串写回设计文档

## Phase 1 后端基建(2 天)

1. `schema.py` 新表 5 张:`qianlong_pool_entries` / `qianlong_signals` /
   `qianlong_trades` / `qianlong_backtest_runs` / `qianlong_live_scan_runs`
   (行表加索引:trade_date、状态;create_all 不补索引,需显式 Index —— 既往教训)
2. `services/qianlong/repository.py`:pool/signals/trades 读写三件套
3. 信号状态机 `services/qianlong/signal_tracker.py`:
   watch → touched(现价≥昨收×1.08)→ confirmed(次分钟仍≥触发价)→ entered(模拟买价=现价×1.005);
   skipped(高开≥8%/11:30 后/排序落选);EOD 定版 sealed/failed
4. 分钟扫描 `services/qianlong/live_scan.py`:复用现货缓存,只扫池内;
   批次 `qianlong_live_scan` 注册进调度(09:30~11:30 每分钟)
5. EOD 链尾部 job:次日池计算 + 在持断板检查 + 退出价回填(次日开盘/断板日开盘)+
   交割单生成(未封板/未连板 → T+1 开盘卖;连板持有,断板日开盘卖)
6. `api/qianlong.py` 七端点(设计文档 §6),注册 `api/router.py`

## Phase 2 回测引擎产品化(1.5 天)

1. `services/qianlong/backtest.py`:移植 `fb_final_binary.py` 日线回放管线
   (触发/进场滑点/三卖出规则/除权剔除/双段切分),固定参数 = v4
2. 物化报告:汇总/月度 41 行/分段/模拟仓(每日≤3 笔,高开 2~6% 优先,等权)/
   熔断叠加对照;写 `qianlong_backtest_runs`(id=1)+ rules_version
3. `POST /backtest/rebuild` 后台线程 + 409 去重 + `/backtest/status` 阶段进度
4. 对账:全样本 = 6,205 笔/+2.42%/50.7%;高开 2~6% 子集 = 2,014 笔/+5.12%/69.6%
   (验收 2);分钟覆盖期信号 vs `fb_final_binary.py` 一致率 ≥98%(验收 3)
5. 调度批 `qianlong_backtest_2230` 每日增量物化

## Phase 3 前端四页签(2.5 天)

1. `frontend/src/features/qianlong/`:`QianlongLiveView` / `QianlongBacktestView` /
   `QianlongLedgerView` / `QianlongGuideView` + `api/qianlong.ts` 客户端
2. `FirstBoardPage.tsx` 重构为四页签容器(照 LowSuctionPage:22-31),
   `ShortTermResearchPage` 默认 tab 指向它;旧榜表格移入 live 页辅助区
3. live 页:状态条(时段/计数/当月盈亏/熔断提示)+ 主表状态徽章与「先做」标记 +
   高开≥8% 灰显;30s 轮询
4. 复制按钮:「复制同花顺条件」(copyText 模式 + toast),文案取自 `GET /rules`
   响应(后端单一事实源);「盘中执行要点」折叠卡
5. guide 页:静态文案(四组 18 条 + 数据支撑 + 已证伪清单 + 风险声明),
   配 `qianlongGuideContent.spec.ts` 防漂移断言(低吸 spec 模式)
6. 设计系统 v3.1 终端蓝,零动画铁律,数字 JetBrains Mono

## Phase 4 联调验收上线(1 天)

1. 验收清单 1~7 全跑(设计文档 §8),含三案例行为抽查
   (智光电气/雪龙集团/天安新材)
2. `docker compose up --build` 全链路;调度日志确认三批次注册与首跑成功
3. 线上发布:ghcr 镜像纪律,发版后 reconcile 日志确认物化无漂移
4. 更新 `requirements/README.md` Current decision(潜龙首板不再是"无状态实时榜")

## 里程碑与工作量

| 阶段 | 内容 | 工作量 | 完成标志 |
|---|---|---|---|
| P0 | 口径对账 + 问财实测 | 0.5d | 池 5 日全对、条件串定稿 |
| P1 | 后端基建 | 2d | 七端点通,扫描/EOD 两链跑通 |
| P2 | 回测产品化 | 1.5d | 回测对账达标,重建可用 |
| P3 | 前端四页签 | 2.5d | 四页签齐,复制按钮可用 |
| P4 | 验收上线 | 1d | 验收 1~7 全过,线上发布 |

合计约 7.5 个工作日。P0→P1 有依赖;P2 与 P3 可并行;P3 的 guide 文案可随时先写。
