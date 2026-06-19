import type { StockQuote } from "@/api/types";
import {
  formatPrice,
  formatPct,
  formatAmount,
  formatMarketCap,
  priceColorClass,
  dataSourceLabel,
} from "@/lib/utils";
import { Badge } from "@/components/ui/badge";

interface StockQuoteHeaderProps {
  quote: StockQuote;
  sealInfo?: {
    limit_amount?: number | null;
    limit_pool_type?: string;
    continuous_limit_up_count?: number | null;
  } | null;
}

export function StockQuoteHeader({ quote, sealInfo }: StockQuoteHeaderProps) {
  const colorClass = priceColorClass(quote.change_pct);

  return (
    <div className="space-y-3">
      {/* Title row */}
      <div className="flex flex-wrap items-center gap-2 sm:gap-3">
        <h1 className="font-display break-words text-2xl font-bold leading-tight">{quote.name}</h1>
        <span className="text-sm text-muted-foreground font-mono break-all">
          {quote.vt_symbol}
        </span>
        <Badge variant="outline">{stockBoardLabel(quote.board, quote.board_label, quote.vt_symbol)}</Badge>
        <Badge variant="outline">{quote.exchange}</Badge>
        {quote.industry && (
          <Badge variant="secondary">{quote.industry}</Badge>
        )}
        {sealInfo?.continuous_limit_up_count != null && sealInfo.continuous_limit_up_count > 0 && (
          <Badge variant="destructive">{sealInfo.continuous_limit_up_count}连板</Badge>
        )}
      </div>

      {/* Price row */}
      <div className="flex flex-wrap items-baseline gap-4">
        <span className={`font-display text-4xl font-bold tabular-nums ${colorClass}`}>
          {formatPrice(quote.last_price)}
        </span>
        <span className={`text-lg tabular-nums ${colorClass}`}>
          {quote.change != null
            ? `${quote.change > 0 ? "+" : ""}${quote.change.toFixed(2)}`
            : "--"}
        </span>
        <span className={`text-lg tabular-nums ${colorClass}`}>
          {formatPct(quote.change_pct)}
        </span>
      </div>

      {/* Detail grid */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-3 md:grid-cols-5 lg:grid-cols-8">
        <QuoteField label="开盘" value={formatPrice(quote.open_price)} />
        <QuoteField label="最高" value={formatPrice(quote.high_price)} />
        <QuoteField label="最低" value={formatPrice(quote.low_price)} />
        <QuoteField label="昨收" value={formatPrice(quote.previous_close)} />
        <QuoteField label="成交额" value={formatAmount(quote.turnover)} />
        <QuoteField label="换手率" value={quote.turnover_rate != null ? `${quote.turnover_rate.toFixed(2)}%` : "--"} />
        <QuoteField label="量比" value={quote.volume_ratio != null ? quote.volume_ratio.toFixed(2) : "--"} />
        {sealInfo?.limit_amount != null && (
          <QuoteField label="封单" value={formatAmount(sealInfo.limit_amount)} />
        )}
        <QuoteField label="市值" value={formatMarketCap(quote.market_cap)} />
        <QuoteField label="PE" value={quote.pe != null ? quote.pe.toFixed(2) : "--"} />
        <QuoteField label="PB" value={quote.pb != null ? quote.pb.toFixed(2) : "--"} />
        <QuoteField label="成交量" value={quote.volume != null ? `${(quote.volume / 10000).toFixed(0)}万手` : "--"} />
        <QuoteField label="地区" value={quote.area ?? "--"} />
        <QuoteField label="数据" value={dataSourceLabel(quote.source)} />
      </div>
    </div>
  );
}

function stockBoardLabel(board?: string | null, boardLabel?: string | null, vtSymbol?: string | null) {
  if (boardLabel) return boardLabel;
  if (board === "main") return "主板";
  if (board === "chinext") return "创业板";
  if (board === "star") return "科创板";
  if (board === "bse") return "北交所";
  const text = vtSymbol?.toUpperCase() ?? "";
  const [symbol, exchange = ""] = text.split(".");
  if (exchange === "BSE" || exchange === "BJ" || /^(8|4|920)/.test(symbol)) return "北交所";
  if (symbol.startsWith("688")) return "科创板";
  if (symbol.startsWith("300") || symbol.startsWith("301")) return "创业板";
  if (exchange === "SSE" || exchange === "SZSE") return "主板";
  return "其他";
}

function QuoteField({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <span className="text-muted-foreground">{label}</span>
      <p className="break-words tabular-nums font-medium">{value}</p>
    </div>
  );
}
