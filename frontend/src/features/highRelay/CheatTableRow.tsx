import type { HprCheatRow } from "@/api/highRelay";
import { cn } from "@/lib/utils";

/** 速查表行(规则页主表与答题讲解卡共用渲染;数据=后端 contracts.CHEAT_ROWS)。
 *  列色与规则页一致:地基阳红/阴绿/中性灰,「不看/—」弱化,今天开主色加粗。
 *  showName=false 供答题卡用(子项全名已在徽章上,表格不再重复口诀列)。 */
export function CheatTableRow({ row, showName = true }: { row: HprCheatRow; showName?: boolean }) {
  const yangCls = row.yang.includes("阳") && !row.yang.includes("阴")
    ? "text-rise"
    : row.yang.includes("阴") && !row.yang.includes("阳")
      ? "text-fall"
      : "text-muted-foreground";
  return (
    <tr className="border-b border-muted/40">
      {showName ? (
        <td className="py-1.5 pr-3 font-medium whitespace-nowrap">{row.name}</td>
      ) : null}
      <td className={cn("py-1.5 pr-3 font-medium whitespace-nowrap", yangCls)}>{row.yang}</td>
      <td
        className={cn(
          "py-1.5 pr-3 font-mono whitespace-nowrap",
          (row.b1 === "不看" || row.b1 === "—") && "text-muted-foreground/50",
        )}
      >
        {row.b1}
      </td>
      <td className="py-1.5 pr-3 font-mono whitespace-nowrap">{row.b2}</td>
      <td
        className={cn(
          "py-1.5 pr-3 font-mono whitespace-nowrap",
          (row.b3 === "不看" || row.b3 === "—") && "text-muted-foreground/50",
        )}
      >
        {row.b3}
      </td>
      <td className="py-1.5 pr-3 font-mono font-semibold text-primary whitespace-nowrap">{row.today}</td>
      <td className="py-1.5 pr-3 font-mono text-muted-foreground">{row.ground ?? "—"}</td>
      <td className="py-1.5 font-mono text-[11px] text-muted-foreground whitespace-nowrap">{row.stat}</td>
    </tr>
  );
}
