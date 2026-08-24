import { cn } from "@/lib/utils";

/** v6 底盘分类徽章:B 类(含 AB)高亮为优先色,A 类灰底。 */
export function ChassisBadge({
  tag,
  priority = false,
}: {
  tag: string | null | undefined;
  priority?: boolean;
}) {
  if (!tag) return null;
  const isB = tag.includes("B");
  return (
    <span
      className={cn(
        "rounded px-1 py-0.5 text-[10px] font-medium",
        isB ? "bg-primary/15 text-primary" : "bg-muted/60 text-muted-foreground",
      )}
      title={isB ? "B类 · 小阳建仓(优先)" : "A类 · 全新急建仓"}
    >
      {tag}{isB && priority ? "·优先" : ""}
    </span>
  );
}
