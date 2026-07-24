import { cn } from "@/lib/utils";

/** 章节头：mono 编号 + 中文标题 + 英文代号，把长回测页变成有顺序的报告 */
export function PanelHead({
  no,
  zh,
  en,
  note,
  aside,
  accent = false,
}: {
  no: string;
  zh: string;
  en: string;
  note?: string;
  aside?: string;
  accent?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-baseline gap-x-2 gap-y-0.5 border-b px-3 py-2 sm:px-4",
        accent ? "bg-primary/[0.05]" : "bg-muted/20",
      )}
    >
      <span className="font-mono text-[10px] font-semibold tracking-[0.15em] text-primary">{no}</span>
      <h2 className="text-sm font-semibold">{zh}</h2>
      <span className="eyebrow">{en}</span>
      {note && <span className="text-[11px] text-muted-foreground">{note}</span>}
      {aside && <span className="ml-auto text-xs tabular-nums text-muted-foreground">{aside}</span>}
    </div>
  );
}
