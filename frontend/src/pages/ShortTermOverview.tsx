import { ArrowRight, GraduationCap, Swords, Undo2 } from "lucide-react";

import { cn } from "@/lib/utils";

/** 短线研究 · 主线总览(默认落地):三主线的定位/成色/入口。
 * 数字 = E0 保守口径(持有到断板),2023-01~2026-09 全市场日线回放,无滑点。 */

type LineCard = {
  research: string;
  icon: typeof Swords;
  tag: string;
  tagClass: string;
  title: string;
  desc: string;
  monthly: string;
  yearly: { year: string; perTrade: string; total: string }[];
  quiz: "ready" | "none";
};

const LINES: LineCard[] = [
  {
    research: "high-relay",
    icon: Swords,
    tag: "主力",
    tagClass: "bg-primary/15 text-primary ring-1 ring-primary/40",
    title: "高位接力",
    desc: "高位连板票的接力打板:月均 4.2 笔,单笔质量与频率双优,资金主力放这里",
    monthly: "月均 4.2 笔 · 79% 月份为正 · 最差月 -39.5%",
    yearly: [
      { year: "2023", perTrade: "+3.75", total: "+116%" },
      { year: "2024", perTrade: "+8.61", total: "+482%" },
      { year: "2025", perTrade: "+11.10", total: "+522%" },
      { year: "2026", perTrade: "+6.68", total: "+381%" },
    ],
    quiz: "ready",
  },
  {
    research: "fanbao",
    icon: Undo2,
    tag: "补充",
    tagClass: "bg-muted text-muted-foreground ring-1 ring-border",
    title: "断板反包",
    desc: "断板 1~3 天的浅断快反包:月均 3.2 笔,分年稳定,补足信号供给",
    monthly: "月均 3.2 笔 · 63% 月份为正 · 最差月 -21.0%",
    yearly: [
      { year: "2023", perTrade: "+3.80", total: "+80%" },
      { year: "2024", perTrade: "+3.69", total: "+177%" },
      { year: "2025", perTrade: "+4.38", total: "+206%" },
      { year: "2026", perTrade: "+3.68", total: "+107%" },
    ],
    quiz: "ready",
  },
];

export function ShortTermOverview({ onSelect }: { onSelect: (research: string, view?: string) => void }) {
  return (
    <div className="space-y-4">
      <section className="rounded-lg border px-4 py-3">
        <div className="text-sm font-semibold">短线打板 · 双主线</div>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          每年每笔收益全部 ≥3%(最差年份口径),月月有信号;两线同票同日零重叠,互不打架,资金按主力→补充分配。
          收益 = E0 保守口径(持有到断板收盘),2023-01~2026-09 全市场日线回放,无滑点,实盘按七至八折预期。
        </p>
      </section>

      <div className="grid gap-3 lg:grid-cols-2">
        {LINES.map((line) => {
          const Icon = line.icon;
          return (
            <section key={line.research} className="flex flex-col rounded-lg border px-4 py-3">
              <div className="flex items-center gap-2">
                <Icon size={16} />
                <span className="text-sm font-semibold">{line.title}</span>
                <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-semibold", line.tagClass)}>
                  {line.tag}
                </span>
              </div>
              <p className="mt-1.5 text-xs leading-5 text-muted-foreground">{line.desc}</p>
              <div className="mt-2 text-[11px] text-muted-foreground">{line.monthly}</div>
              <div className="mt-3 grid grid-cols-4 gap-1 border-t pt-2.5">
                {line.yearly.map((y) => (
                  <div key={y.year} className="text-center">
                    <div className="text-[10px] text-muted-foreground">{y.year}</div>
                    <div className="font-mono text-xs font-semibold text-rise tabular-nums">{y.perTrade}</div>
                    <div className="font-mono text-[10px] text-muted-foreground tabular-nums">{y.total}</div>
                  </div>
                ))}
              </div>
              <div className="mt-auto flex items-center gap-2 pt-3">
                <button
                  type="button"
                  className="flex h-8 items-center gap-1 rounded-md bg-primary px-3 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
                  onClick={() => onSelect(line.research)}
                >
                  进入 <ArrowRight size={13} />
                </button>
                {line.quiz === "ready" ? (
                  <button
                    type="button"
                    className="flex h-8 items-center gap-1 rounded-md border px-3 text-xs font-medium text-muted-foreground hover:bg-muted/40"
                    onClick={() => onSelect(line.research, "quiz")}
                  >
                    <GraduationCap size={13} /> 答题训练
                  </button>
                ) : (
                  <span className="text-[10px] text-muted-foreground/60">答题训练待建</span>
                )}
              </div>
            </section>
          );
        })}
      </div>

    </div>
  );
}
