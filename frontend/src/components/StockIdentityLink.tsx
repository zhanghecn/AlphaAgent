import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";

interface StockIdentityLinkProps {
  name?: string | null;
  vtSymbol?: string | null;
  board?: string | null;
  boardLabel?: string | null;
  meta?: string | null;
  link?: boolean;
  className?: string;
}

export function StockIdentityLink({
  name,
  vtSymbol,
  board,
  boardLabel,
  meta,
  link = true,
  className,
}: StockIdentityLinkProps) {
  const symbol = vtSymbol?.trim() ?? "";
  const title = name?.trim() || symbol || "--";
  const boardText = boardLabel?.trim() || stockBoardLabel(board, symbol);
  const details = [name?.trim() ? symbol : "", meta?.trim() ?? ""].filter(Boolean);
  const content = (
    <>
      <div className="flex min-w-0 items-center gap-1.5">
        <div className={cn("truncate font-medium", link && symbol && "text-primary group-hover:underline")}>
          {title}
        </div>
        {boardText && (
          <span className="shrink-0 rounded-md border px-1.5 py-0.5 text-[11px] leading-4 text-muted-foreground">
            {boardText}
          </span>
        )}
      </div>
      {details.length > 0 && (
        <div className="truncate text-xs text-muted-foreground">
          {details.join(" · ")}
        </div>
      )}
    </>
  );

  if (!link || !symbol) {
    return <div className={cn("min-w-0", className)}>{content}</div>;
  }

  return (
    <Link
      className={cn("group block min-w-0 rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", className)}
      title={`打开 ${title}`}
      to={`/stocks/${encodeURIComponent(symbol)}`}
    >
      {content}
    </Link>
  );
}

function stockBoardLabel(board?: string | null, vtSymbol?: string | null) {
  const normalized = board?.trim().toLowerCase();
  if (normalized) return BOARD_LABELS[normalized] ?? "其他";
  const text = vtSymbol?.trim().toUpperCase() ?? "";
  const [symbol, exchange = ""] = text.split(".");
  if (!symbol) return "";
  if (exchange === "BSE" || exchange === "BJ" || /^(8|4|920)/.test(symbol)) return "北交所";
  if (symbol.startsWith("688")) return "科创板";
  if (symbol.startsWith("300") || symbol.startsWith("301")) return "创业板";
  if ((exchange === "SSE" && symbol.startsWith("000")) || (exchange === "SZSE" && symbol.startsWith("399"))) return "指数";
  if (exchange === "SSE" || exchange === "SZSE" || /^(600|601|603|605|000|001|002|003)/.test(symbol)) return "主板";
  return "其他";
}

const BOARD_LABELS: Record<string, string> = {
  main: "主板",
  chinext: "创业板",
  star: "科创板",
  bse: "北交所",
  index: "指数",
  unknown: "其他",
};
