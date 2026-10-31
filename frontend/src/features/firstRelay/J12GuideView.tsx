import { useQuery } from "@tanstack/react-query";

import { fetchFirstRelayRules, type J12RulesPayload } from "@/api/firstRelay";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { cn } from "@/lib/utils";

const LEVEL_TONE: Record<string, string> = {
  出手: "bg-rise/15 text-rise ring-1 ring-rise/40",
  综合: "bg-primary/15 text-primary ring-1 ring-primary/40",
};

export function J12GuideView() {
  const query = useQuery({ queryKey: ["j12Rules"], queryFn: fetchFirstRelayRules, staleTime: 300_000 });
  if (query.isLoading && !query.data) return <div className="py-5"><LoadingState rows={6} /></div>;
  if (query.isError || !query.data) return <ErrorState message="一接二规则契约暂时不可用" />;
  const g = query.data;
  const t = g.rules_text;
  return (
    <div className="space-y-4">
      <section className="rounded-lg border bg-primary/5 p-4">
        <div className="mb-2 flex items-baseline justify-between">
          <h3 className="text-sm font-semibold text-foreground">综合最终规则({g.rules_version})</h3>
          <span className="text-xs text-muted-foreground">{g.main_window.note}</span>
        </div>
        <p className="whitespace-pre-line font-mono text-sm leading-7 text-primary">{t.koujue}</p>
        <p className="mt-2 text-xs leading-6 text-muted-foreground">{t.entry}</p>
      </section>

      <section className="rounded-lg border p-4">
        <h3 className="mb-3 text-sm font-semibold">速查表（同票同日去重）</h3>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="border-b bg-muted/30 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">口诀</th>
                <th className="px-3 py-2 text-left font-medium">条件</th>
                <th className="px-3 py-2 text-left font-medium">级别</th>
                <th className="px-3 py-2 text-left font-medium">六年成绩</th>
              </tr>
            </thead>
            <tbody>
              {g.cheat_rows.map((row) => (
                <tr key={row.口诀} className="border-b last:border-b-0">
                  <td className="px-3 py-2.5 font-medium">{row.口诀}</td>
                  <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">{row.条件}</td>
                  <td className="px-3 py-2.5">
                    <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium", LEVEL_TONE[row.级别])}>
                      {row.级别}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 font-mono text-xs tabular-nums">{row.六年}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-lg border p-4 text-sm">
          <h3 className="mb-2 font-semibold">机制(为什么赚钱)</h3>
          <p className="leading-6 text-muted-foreground">{t.mechanism}</p>
          <h3 className="mb-2 mt-4 font-semibold">执行</h3>
          <p className="leading-6 text-muted-foreground">{t.position}</p>
        </section>
        <section className="rounded-lg border p-4 text-sm">
          <h3 className="mb-2 font-semibold">卖出纪律(纯断板尾盘)</h3>
          <p className="leading-6 text-muted-foreground">{t.sell}</p>
          {t.avoid.length > 0 ? (
            <ul className="mt-4 list-disc space-y-1 pl-5 text-muted-foreground">
              {t.avoid.map((a) => <li key={a}>{a}</li>)}
            </ul>
          ) : null}
        </section>
      </div>

      <section className="rounded-lg border border-primary/30 bg-primary/5 p-4 text-sm">
        <h3 className="mb-2 font-semibold text-primary">历史表现与边界</h3>
        <p className="leading-6 text-muted-foreground">{t.honest}</p>
      </section>
    </div>
  );
}

export type { J12RulesPayload };
