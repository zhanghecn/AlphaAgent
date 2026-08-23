# AlphaAgent Requirements Index

这里保存当前仍有产品需求价值的文档。运行事实以源码和测试为准；研究诊断
直接在会话中交付，不维护仓库内的记忆或过程报告。

## Current decision

- 短线产品为三条按交易日保存的产品线：低吸（实时推荐/回测/历史交割单/规则说明）、
  潜龙首板（同上四页签 + 同花顺条件复制，2026-08-23 已实现；
  设计见 `qianlong_first_board_design.md`、实施见 `qianlong_first_board_implementation_plan.md`，
  策略口径 = `量化因子研究/潜龙首板/潜龙首板条件定稿.md` v4）、
  趋势弱转强（同上四页签 + A1/A2/B 三串同花顺条件复制，2026-08-23 已实现；
  设计见 `weak_to_strong_v2_design.md`、实施见 `weak_to_strong_v2_implementation_plan.md`，
  策略口径 = `量化因子研究/低吸研究/趋势低吸研究-弱转强v2.md` 定稿 v2）。
- 旧打板研究及其计划、回测、调度和服务均已移除；需要审计旧版本时使用 Git 历史，不恢复为当前入口。
