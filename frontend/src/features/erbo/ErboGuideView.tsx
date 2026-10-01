import { useQuery } from "@tanstack/react-query";

import { fetchErboRules } from "@/api/erbo";
import { cn } from "@/lib/utils";

export function ErboGuideView() {
  const query = useQuery({ queryKey: ["erboRules"], queryFn: fetchErboRules, staleTime: 300_000 });
  const data = query.data;
  if (query.isLoading && !data) return <div className="py-5 text-sm text-muted-foreground">加载规则…</div>;
  if (query.isError || !data) {
    return <div className="py-5 text-sm text-fall">规则契约暂时不可用</div>;
  }
  return (
    <div className="space-y-4">
      {data.rules.map((group) => (
        <section key={group.group} className="rounded-lg border px-4 py-3">
          <div className="mb-2 text-sm font-semibold">{group.title}</div>
          <ol className="space-y-2">
            {group.items.map((item) => (
              <li key={item.no} className="text-xs leading-6">
                <span className="mr-1.5 inline-block h-5 w-5 rounded bg-primary/10 text-center text-[11px] font-semibold leading-5 text-primary">
                  {item.no}
                </span>
                <span className="text-foreground">{item.rule}</span>
                {item.evidence ? (
                  <span className="ml-2 text-muted-foreground">（{item.evidence}）</span>
                ) : null}
              </li>
            ))}
          </ol>
        </section>
      ))}

      <section className="rounded-lg border px-4 py-3">
        <div className="mb-2 text-sm font-semibold">盘中操作手册</div>
        <ul className="list-disc space-y-1 pl-5 text-xs leading-6 text-muted-foreground">
          {data.intraday_playbook.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </section>

      <section className="rounded-lg border px-4 py-3">
        <div className="mb-2 text-sm font-semibold">风险与边界</div>
        <ul className="list-disc space-y-1 pl-5 text-xs leading-6 text-amber-600/90">
          {data.risk_notes.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </section>

      <section className="rounded-lg border px-4 py-3">
        <div className="mb-2 text-sm font-semibold">留档未收编(防翻案)</div>
        <ul className="list-disc space-y-1 pl-5 text-xs leading-6 text-muted-foreground/80">
          {data.falsified_rules.map((line) => (
            <li key={line} className={cn("text-muted-foreground")}>{line}</li>
          ))}
        </ul>
      </section>
    </div>
  );
}
