// 动效原语库 barrel：全站动效统一入口。
// 所有原语内部读 useReducedMotion()，reduce-motion 时退化为瞬时渲染（保险层 2）。
export { Reveal } from "./Reveal";
export { StaggerList, StaggerItem } from "./Stagger";
export { CountUp } from "./CountUp";
export { PulseNumber } from "./PulseNumber";
export { PageTransition } from "./PageTransition";
export { LiftCard } from "./LiftCard";
export { KpiNumber } from "./KpiNumber";
export { formatAnimatedValue, type AnimFormat } from "./format";
