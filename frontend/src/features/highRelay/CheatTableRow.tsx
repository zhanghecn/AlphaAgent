import type { HprCheatRow } from "@/api/highRelay";
import { cn } from "@/lib/utils";

/** 速查表行(规则页主表与答题讲解卡共用渲染;数据=后端 contracts.CHEAT_ROWS)。
 *  列色与规则页一致:组阳红/阴绿/中性灰,「不看/—」弱化,今天开主色加粗。
 *  showName=false 供答题卡用(子项全名已在徽章上,表格不再重复口诀列)。
 *  failCols=红列键集合(q34 miss 题「哪里没匹配上」:yang/b1/b2/b3/today/ground,
 *  样式与题面判分红格同款 bg-fall/10+ring+红字)。 */
const FAIL_TD = "bg-fall/10 ring-1 ring-inset ring-fall/50";

export function CheatTableRow({
  row,
  showName = true,
  failCols,
  statText,
}: {
  row: HprCheatRow;
  showName?: boolean;
  failCols?: string[];
  statText?: string;   // 成绩列覆盖文本(动态口诀组传近12月动态成绩;缺省=row.stat研究锚定)
}) {
  const fail = (col: string) => (failCols ?? []).includes(col);
  const yangCls = fail("yang")
    ? "font-semibold text-fall"
    : row.yang.includes("阳") && !row.yang.includes("阴")
      ? "text-rise"
      : row.yang.includes("阴") && !row.yang.includes("阳")
        ? "text-fall"
        : "text-muted-foreground";
  return (
    <tr className="border-b border-muted/40">
      {showName ? (
        <td className="py-1.5 pr-3 font-medium whitespace-nowrap">{row.name}</td>
      ) : null}
      <td className={cn("py-1.5 pr-3 font-medium whitespace-nowrap rounded", yangCls, fail("yang") && FAIL_TD)}>{row.yang}</td>
      <td
        className={cn(
          "py-1.5 pr-3 font-mono whitespace-nowrap rounded",
          !fail("b1") && (row.b1 === "不看" || row.b1 === "—") && "text-muted-foreground/50",
          fail("b1") && ["font-semibold", "text-fall", FAIL_TD],
        )}
      >
        {row.b1}
      </td>
      <td className={cn("py-1.5 pr-3 font-mono whitespace-nowrap rounded", fail("b2") && ["font-semibold", "text-fall", FAIL_TD])}>{row.b2}</td>
      <td
        className={cn(
          "py-1.5 pr-3 font-mono whitespace-nowrap rounded",
          !fail("b3") && (row.b3 === "不看" || row.b3 === "—") && "text-muted-foreground/50",
          fail("b3") && ["font-semibold", "text-fall", FAIL_TD],
        )}
      >
        {row.b3}
      </td>
      <td className={cn("py-1.5 pr-3 font-mono font-semibold whitespace-nowrap rounded", fail("today") ? ["text-fall", FAIL_TD] : "text-primary")}>{row.today}</td>
      <td className={cn("py-1.5 pr-3 font-mono whitespace-nowrap rounded text-muted-foreground", fail("ground") && ["font-semibold", "text-fall", FAIL_TD])}>{row.ground ?? "—"}</td>
      <td className="py-1.5 font-mono text-[11px] text-muted-foreground whitespace-nowrap">{statText ?? row.stat}</td>
    </tr>
  );
}
