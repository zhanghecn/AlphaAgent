import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getPaginationRowModel,
  flexRender,
  type SortingState,
  type ColumnDef,
} from "@tanstack/react-table";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchStocks } from "@/api/stocks";
import type { StockQuote } from "@/api/types";
import {
  formatPrice,
  formatPct,
  formatAmount,
  formatMarketCap,
  priceColorClass,
} from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { Search, ArrowUpDown, ArrowUp, ArrowDown, ChevronLeft, ChevronRight, Database, Radio } from "lucide-react";

export function StockTable() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [sorting, setSorting] = useState<SortingState>([
    { id: "market_cap", desc: true },
  ]);
  const [page, setPage] = useState(1);
  const pageSize = 50;

  const sortParam = sorting[0]
    ? sorting[0].id === "market_cap"
      ? "mktcap"
      : sorting[0].id === "turnover"
        ? "amount"
        : sorting[0].id === "change_pct"
          ? "changepercent"
        : sorting[0].id === "turnover_rate"
            ? "turnoverratio"
            : sorting[0].id === "volume_ratio"
              ? "volume_ratio"
              : sorting[0].id === "return_5d"
                ? "return_5d"
                : sorting[0].id === "return_10d"
                  ? "return_10d"
                  : sorting[0].id === "return_20d"
                    ? "return_20d"
              : "mktcap"
    : "mktcap";

  const orderParam = sorting[0]?.desc ? "desc" : "asc";

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["stocks", appliedSearch, page, sortParam, orderParam],
    queryFn: () =>
      fetchStocks({
        q: appliedSearch || undefined,
        page,
        page_size: pageSize,
        sort: sortParam,
        order: orderParam as "asc" | "desc",
      }),
  });

  const columns = useMemo<ColumnDef<StockQuote>[]>(
    () => [
      {
        accessorKey: "symbol",
        header: "代码",
        cell: ({ getValue }) => (
          <span className="font-mono text-xs">{getValue() as string}</span>
        ),
        size: 80,
      },
      {
        accessorKey: "name",
        header: "名称",
        cell: ({ getValue, row }) => (
          <button
            type="button"
            className="text-left hover:underline font-medium"
            onClick={() => navigate(`/stocks/${row.original.vt_symbol}`)}
          >
            {getValue() as string}
          </button>
        ),
        size: 100,
      },
      {
        accessorKey: "exchange",
        header: "交易所",
        size: 70,
      },
      {
        accessorKey: "last_price",
        header: "最新价",
        cell: ({ getValue }) => (
          <span className="tabular-nums">{formatPrice(getValue() as number | null)}</span>
        ),
        size: 80,
      },
      {
        accessorKey: "change_pct",
        header: ({ column }) => (
          <button
            type="button"
            className="flex items-center gap-1"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          >
            涨跌幅
            <ArrowUpDown size={14} />
          </button>
        ),
        cell: ({ getValue }) => {
          const val = getValue() as number | null;
          return (
            <span className={`tabular-nums font-medium ${priceColorClass(val)}`}>
              {formatPct(val)}
            </span>
          );
        },
        size: 90,
      },
      {
        accessorKey: "return_5d",
        header: ({ column }) => (
          <SortableColumnButton label="5日" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")} sorted={column.getIsSorted()} />
        ),
        cell: ({ getValue }) => (
          <span className={`tabular-nums ${priceColorClass(getValue() as number | null)}`}>
            {formatPct(getValue() as number | null)}
          </span>
        ),
        size: 76,
      },
      {
        accessorKey: "return_10d",
        header: ({ column }) => (
          <SortableColumnButton label="10日" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")} sorted={column.getIsSorted()} />
        ),
        cell: ({ getValue }) => (
          <span className={`tabular-nums ${priceColorClass(getValue() as number | null)}`}>
            {formatPct(getValue() as number | null)}
          </span>
        ),
        size: 76,
      },
      {
        accessorKey: "return_20d",
        header: ({ column }) => (
          <SortableColumnButton label="20日" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")} sorted={column.getIsSorted()} />
        ),
        cell: ({ getValue }) => (
          <span className={`tabular-nums ${priceColorClass(getValue() as number | null)}`}>
            {formatPct(getValue() as number | null)}
          </span>
        ),
        size: 76,
      },
      {
        accessorKey: "turnover",
        header: ({ column }) => (
          <button
            type="button"
            className="flex items-center gap-1"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          >
            成交额
            <ArrowUpDown size={14} />
          </button>
        ),
        cell: ({ getValue }) => (
          <span className="tabular-nums">{formatAmount(getValue() as number | null)}</span>
        ),
        size: 90,
      },
      {
        accessorKey: "turnover_rate",
        header: ({ column }) => (
          <button
            type="button"
            className="flex items-center gap-1"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          >
            换手率
            <ArrowUpDown size={14} />
          </button>
        ),
        cell: ({ getValue }) => {
          const val = getValue() as number | null;
          return <span className="tabular-nums">{val != null ? `${val.toFixed(2)}%` : "--"}</span>;
        },
        size: 80,
      },
      {
        accessorKey: "volume_ratio",
        header: ({ column }) => (
          <button
            type="button"
            className="flex items-center gap-1"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          >
            量比
            <ArrowUpDown size={14} />
          </button>
        ),
        cell: ({ getValue }) => {
          const val = getValue() as number | null;
          return <span className="tabular-nums">{val != null ? val.toFixed(2) : "--"}</span>;
        },
        size: 72,
      },
      {
        accessorKey: "market_cap",
        header: ({ column }) => (
          <button
            type="button"
            className="flex items-center gap-1"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          >
            市值
            <ArrowUpDown size={14} />
          </button>
        ),
        cell: ({ getValue }) => (
          <span className="tabular-nums">{formatMarketCap(getValue() as number | null)}</span>
        ),
        size: 90,
      },
      {
        accessorKey: "pe",
        header: "PE",
        cell: ({ getValue }) => {
          const val = getValue() as number | null;
          return <span className="tabular-nums">{val != null ? val.toFixed(2) : "--"}</span>;
        },
        size: 60,
      },
      {
        accessorKey: "pb",
        header: "PB",
        cell: ({ getValue }) => {
          const val = getValue() as number | null;
          return <span className="tabular-nums">{val != null ? val.toFixed(2) : "--"}</span>;
        },
        size: 60,
      },
    ],
    [navigate],
  );

  const table = useReactTable({
    data: data?.items ?? [],
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    manualPagination: true,
    manualSorting: true,
    pageCount: data?.total ? Math.ceil(data.total / pageSize) : -1,
  });

  function handleSearch() {
    setPage(1);
    setAppliedSearch(search);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") handleSearch();
  }

  if (isLoading) return <LoadingState rows={8} />;
  if (isError)
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "加载股票列表失败"}
        onRetry={() => refetch()}
      />
    );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b pb-3">
        <div className="flex w-full items-center gap-2 sm:w-auto">
          <Input
            placeholder="搜索代码、名称或拼音线索"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={handleKeyDown}
            className="min-w-0 flex-1 sm:w-64"
          />
          <Button variant="outline" size="sm" onClick={handleSearch}>
            <Search size={16} />
          </Button>
        </div>
        <DataOriginSummary data={data} />
      </div>

      {data?.items.length === 0 ? (
        <EmptyState message="暂无股票数据" description="后端行情数据正在加载或暂时不可用" />
      ) : (
        <>
          <div className="overflow-x-auto rounded-md border">
          <Table className="min-w-[1190px]">
            <TableHeader>
              {table.getHeaderGroups().map((hg) => (
                <TableRow key={hg.id}>
                  {hg.headers.map((header) => (
                    <TableHead
                      key={header.id}
                      style={{ width: header.getSize(), minWidth: header.getSize() }}
                    >
                      {header.isPlaceholder
                        ? null
                        : flexRender(header.column.columnDef.header, header.getContext())}
                    </TableHead>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  className="cursor-pointer"
                  onClick={() => navigate(`/stocks/${row.original.vt_symbol}`)}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              第 {page} 页
              {data?.total != null ? ` / 共 ${data.total} 条` : ""}
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                <ChevronLeft size={16} />
              </Button>
              <span className="text-sm tabular-nums">{page}</span>
              <Button
                variant="outline"
                size="sm"
                disabled={!data?.items.length || data.items.length < pageSize}
                onClick={() => setPage((p) => p + 1)}
              >
                <ChevronRight size={16} />
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function SortableColumnButton({ label, onClick, sorted }: { label: string; onClick: () => void; sorted?: false | "asc" | "desc" }) {
  return (
    <button type="button" className="flex items-center gap-1" onClick={onClick}>
      {label}
      {sorted ? (
        sorted === "desc" ? <ArrowDown size={14} /> : <ArrowUp size={14} />
      ) : (
        <ArrowUpDown size={14} className="opacity-40" />
      )}
    </button>
  );
}

function DataOriginSummary({ data }: { data?: import("@/api/types").StockListData }) {
  if (!data) return null;
  const local = data.data_origin === "local_db" || data.source?.startsWith("postgresql");
  const coverage = data.coverage ?? {};
  const rows = typeof coverage.rows === "number" ? coverage.rows : data.total;
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      <Badge variant={local ? "secondary" : "outline"} className="rounded-md gap-1">
        {local ? <Database size={13} /> : <Radio size={13} />}
        {local ? "本地历史库" : "实时公开源"}
      </Badge>
      {data.fallback_used && <Badge variant="outline" className="rounded-md">实时兜底</Badge>}
      <span>{rows != null ? `覆盖 ${rows} 只` : "覆盖数待返回"}</span>
      {data.updated_at && <span>更新 {new Date(data.updated_at).toLocaleTimeString("zh-CN")}</span>}
    </div>
  );
}
