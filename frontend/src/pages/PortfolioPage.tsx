import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Briefcase, FolderPlus, Plus, RefreshCw } from "lucide-react";
import {
  addPortfolioGroupItem,
  autoBuyRecommendations,
  createPortfolioGroup,
  fetchHoldings,
  fetchPortfolioGroupItems,
  fetchPortfolioGroups,
  fetchSimulationAccounts,
  type PortfolioGroup,
  type PortfolioItem,
  type SimulationPosition,
} from "@/api/quant";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn, formatAmount, formatPct, formatPrice, priceColorClass } from "@/lib/utils";

export function PortfolioPage() {
  const queryClient = useQueryClient();
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);
  const [newGroupName, setNewGroupName] = useState("");
  const [newSymbol, setNewSymbol] = useState("");
  const [newReason, setNewReason] = useState("");

  const groupsQuery = useQuery({
    queryKey: ["portfolioGroups"],
    queryFn: fetchPortfolioGroups,
    staleTime: 30_000,
  });

  const groups = groupsQuery.data?.items ?? [];
  const activeGroup = useMemo(() => {
    if (selectedGroupId) return groups.find((group) => group.id === selectedGroupId) ?? null;
    return groups[0] ?? null;
  }, [groups, selectedGroupId]);

  const groupItemsQuery = useQuery({
    queryKey: ["portfolioGroupItems", activeGroup?.id],
    queryFn: () => fetchPortfolioGroupItems(activeGroup!.id),
    enabled: Boolean(activeGroup?.id),
    staleTime: 20_000,
  });

  const accountsQuery = useQuery({
    queryKey: ["simulationAccounts"],
    queryFn: fetchSimulationAccounts,
    staleTime: 20_000,
  });

  const holdingsQuery = useQuery({
    queryKey: ["portfolioHoldings"],
    queryFn: fetchHoldings,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });

  const createGroupMutation = useMutation({
    mutationFn: () =>
      createPortfolioGroup({
        name: newGroupName.trim(),
        group_type: "manual",
        description: "用户手动维护的持仓分组",
      }),
    onSuccess: () => {
      setNewGroupName("");
      queryClient.invalidateQueries({ queryKey: ["portfolioGroups"] });
    },
  });

  const addItemMutation = useMutation({
    mutationFn: () =>
      addPortfolioGroupItem(activeGroup!.id, {
        vt_symbol: newSymbol.trim().toUpperCase(),
        source: "manual",
        reason: newReason.trim() || "用户手动加入",
      }),
    onSuccess: () => {
      setNewSymbol("");
      setNewReason("");
      queryClient.invalidateQueries({ queryKey: ["portfolioGroupItems", activeGroup?.id] });
    },
  });

  const autoBuyMutation = useMutation({
    mutationFn: () =>
      autoBuyRecommendations({
        account_id: accountsQuery.data?.items[0]?.id,
        limit: 5,
        amount_per_order: 100_000,
        initial_cash: 1_000_000,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["simulationAccounts"] });
      queryClient.invalidateQueries({ queryKey: ["portfolioHoldings"] });
      queryClient.invalidateQueries({ queryKey: ["portfolioGroups"] });
      queryClient.invalidateQueries({ queryKey: ["portfolioGroupItems"] });
    },
  });

  if (groupsQuery.isLoading) return <LoadingState rows={6} />;
  if (groupsQuery.isError) {
    return (
      <ErrorState
        message={groupsQuery.error instanceof Error ? groupsQuery.error.message : "加载持仓分组失败"}
        onRetry={() => groupsQuery.refetch()}
      />
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b pb-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">持仓</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            分组管理自选、量化候选和模拟持仓。这里是独立模块，量化只负责把结果同步过来。
          </p>
        </div>
        <Button onClick={() => autoBuyMutation.mutate()} disabled={autoBuyMutation.isPending}>
          {autoBuyMutation.isPending ? <RefreshCw size={16} className="animate-spin" /> : <Briefcase size={16} />}
          量化候选模拟建仓
        </Button>
      </div>

      <PortfolioSummary
        cash={accountsQuery.data?.items[0]?.cash}
        initialCash={accountsQuery.data?.items[0]?.initial_cash}
        positions={holdingsQuery.data?.items ?? []}
        accountCount={accountsQuery.data?.items.length ?? 0}
      />

      <div className="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
        <section className="space-y-4">
          <GroupList groups={groups} activeId={activeGroup?.id ?? null} onSelect={setSelectedGroupId} />
          <CreateGroupForm
            name={newGroupName}
            onNameChange={setNewGroupName}
            onCreate={() => createGroupMutation.mutate()}
            isCreating={createGroupMutation.isPending}
          />
        </section>

        <section className="space-y-4">
          <GroupItemsPanel
            group={activeGroup}
            items={groupItemsQuery.data?.items ?? []}
            isLoading={groupItemsQuery.isLoading}
            isError={groupItemsQuery.isError}
            onRetry={() => groupItemsQuery.refetch()}
            symbol={newSymbol}
            reason={newReason}
            onSymbolChange={setNewSymbol}
            onReasonChange={setNewReason}
            onAdd={() => addItemMutation.mutate()}
            isAdding={addItemMutation.isPending}
          />
          <SimulationHoldingsPanel
            items={holdingsQuery.data?.items ?? []}
            isLoading={holdingsQuery.isLoading || accountsQuery.isLoading}
            isError={holdingsQuery.isError || accountsQuery.isError}
            onRetry={() => {
              holdingsQuery.refetch();
              accountsQuery.refetch();
            }}
          />
        </section>
      </div>
    </div>
  );
}

function PortfolioSummary({
  cash,
  initialCash,
  positions,
  accountCount,
}: {
  cash?: number;
  initialCash?: number;
  positions: SimulationPosition[];
  accountCount: number;
}) {
  const marketValue = positions.reduce((sum, item) => sum + (item.market_value ?? 0), 0);
  const equity = (cash ?? 0) + marketValue;
  return (
    <section className="grid gap-3 rounded-lg border p-4 text-sm md:grid-cols-5">
      <InfoCell label="账户" value={`${accountCount} 个`} />
      <InfoCell label="现金" value={formatAmount(cash)} />
      <InfoCell label="持仓市值" value={formatAmount(marketValue)} />
      <InfoCell label="总权益" value={formatAmount(equity)} />
      <InfoCell label="收益率" value={formatPct(initialCash ? (equity / initialCash - 1) * 100 : null)} valueClass={priceColorClass(initialCash ? (equity / initialCash - 1) * 100 : null)} />
    </section>
  );
}

function GroupList({
  groups,
  activeId,
  onSelect,
}: {
  groups: PortfolioGroup[];
  activeId: number | null;
  onSelect: (id: number) => void;
}) {
  return (
    <section className="rounded-lg border">
      <div className="border-b px-4 py-3 text-sm font-semibold">分组</div>
      <div className="divide-y">
        {groups.map((group) => (
          <button
            key={group.id}
            type="button"
            className={cn(
              "block w-full px-4 py-3 text-left text-sm hover:bg-muted/50",
              activeId === group.id && "bg-muted"
            )}
            onClick={() => onSelect(group.id)}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">{group.name}</span>
              {group.auto_managed && <span className="rounded-md border px-2 py-0.5 text-xs text-muted-foreground">自动</span>}
            </div>
            {group.description && <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">{group.description}</div>}
          </button>
        ))}
      </div>
    </section>
  );
}

function CreateGroupForm({
  name,
  onNameChange,
  onCreate,
  isCreating,
}: {
  name: string;
  onNameChange: (value: string) => void;
  onCreate: () => void;
  isCreating: boolean;
}) {
  return (
    <section className="rounded-lg border p-4 text-sm">
      <div className="font-medium">新建分组</div>
      <div className="mt-3 flex gap-2">
        <input
          className="h-9 min-w-0 flex-1 rounded-md border bg-background px-2 text-sm"
          value={name}
          onChange={(event) => onNameChange(event.target.value)}
          placeholder="例如：低吸观察"
        />
        <Button size="sm" onClick={onCreate} disabled={!name.trim() || isCreating}>
          {isCreating ? <RefreshCw size={15} className="animate-spin" /> : <FolderPlus size={15} />}
          新建
        </Button>
      </div>
    </section>
  );
}

function GroupItemsPanel({
  group,
  items,
  isLoading,
  isError,
  onRetry,
  symbol,
  reason,
  onSymbolChange,
  onReasonChange,
  onAdd,
  isAdding,
}: {
  group: PortfolioGroup | null;
  items: PortfolioItem[];
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  symbol: string;
  reason: string;
  onSymbolChange: (value: string) => void;
  onReasonChange: (value: string) => void;
  onAdd: () => void;
  isAdding: boolean;
}) {
  if (!group) return <EmptyState message="暂无持仓分组" description="先创建一个分组。" />;
  if (isLoading) return <LoadingState rows={4} />;
  if (isError) return <ErrorState message="加载分组股票失败" onRetry={onRetry} />;

  return (
    <section className="rounded-lg border">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold">{group.name}</h2>
          <div className="mt-1 text-xs text-muted-foreground">{items.length} 只 · {group.auto_managed ? "策略自动维护，可手动补充" : "用户手动维护"}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <input
            className="h-9 w-32 rounded-md border bg-background px-2 text-sm"
            value={symbol}
            onChange={(event) => onSymbolChange(event.target.value)}
            placeholder="600000.SSE"
          />
          <input
            className="h-9 w-56 rounded-md border bg-background px-2 text-sm"
            value={reason}
            onChange={(event) => onReasonChange(event.target.value)}
            placeholder="加入原因"
          />
          <Button size="sm" onClick={onAdd} disabled={!symbol.trim() || isAdding}>
            {isAdding ? <RefreshCw size={15} className="animate-spin" /> : <Plus size={15} />}
            加入
          </Button>
        </div>
      </div>
      {items.length === 0 ? (
        <div className="p-4">
          <EmptyState message="分组为空" description="可以手动加入股票，也可以由量化筛选自动同步候选。" />
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>股票</TableHead>
              <TableHead>来源</TableHead>
              <TableHead>策略</TableHead>
              <TableHead>加入原因</TableHead>
              <TableHead className="text-right">更新时间</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow key={`${item.group_id}-${item.vt_symbol}`}>
                <TableCell>
                  <StockIdentityLink name={item.name} vtSymbol={item.vt_symbol} board={item.board} boardLabel={item.board_label} />
                </TableCell>
                <TableCell>{sourceLabel(item.source)}</TableCell>
                <TableCell className="text-muted-foreground">{item.strategy_id ?? "--"}</TableCell>
                <TableCell className="max-w-[360px] truncate text-muted-foreground">{item.reason ?? "--"}</TableCell>
                <TableCell className="text-right text-xs text-muted-foreground">{formatTime(item.updated_at ?? item.created_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </section>
  );
}

function SimulationHoldingsPanel({
  items,
  isLoading,
  isError,
  onRetry,
}: {
  items: SimulationPosition[];
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
}) {
  if (isLoading) return <LoadingState rows={5} />;
  if (isError) return <ErrorState message="加载模拟持仓失败" onRetry={onRetry} />;

  return (
    <section className="rounded-lg border">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <Briefcase size={16} />
          <h2 className="text-sm font-semibold">模拟持仓明细</h2>
        </div>
        <span className="text-xs text-muted-foreground">30 秒轮询刷新</span>
      </div>
      {items.length === 0 ? (
        <div className="p-4">
          <EmptyState message="暂无模拟持仓" description="可以从量化候选模拟建仓，或后续手动下模拟单。" />
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>股票</TableHead>
              <TableHead className="text-right">成本</TableHead>
              <TableHead className="text-right">现价</TableHead>
              <TableHead className="text-right">数量</TableHead>
              <TableHead className="text-right">浮盈亏</TableHead>
              <TableHead>买入/卖出时机</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow key={`${item.account_id}-${item.vt_symbol}`}>
                <TableCell>
                  <StockIdentityLink
                    name={item.name}
                    vtSymbol={item.vt_symbol}
                    board={item.board}
                    boardLabel={item.board_label}
                    meta={item.account_name ?? "模拟账户"}
                  />
                </TableCell>
                <TableCell className="text-right tabular-nums">{formatPrice(item.cost_price)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatPrice(item.last_price)}</TableCell>
                <TableCell className="text-right tabular-nums">{item.volume.toLocaleString()}</TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(item.floating_pnl_pct))}>
                  <div>{formatAmount(item.floating_pnl)}</div>
                  <div className="text-xs">{formatPct(item.floating_pnl_pct)}</div>
                </TableCell>
                <TableCell className="max-w-[420px] text-xs text-muted-foreground">
                  <div>买入 {formatTime(item.last_buy_time)} · {formatPrice(item.last_buy_price)} · {item.last_buy_volume ?? "--"} 股</div>
                  <div className="mt-1 truncate">依据 {item.last_buy_reason || item.reason || "--"}</div>
                  {item.last_sell_time && (
                    <div className="mt-1">
                      卖出 {formatTime(item.last_sell_time)} · {formatPrice(item.last_sell_price)} · 盈亏{" "}
                      <span className={priceColorClass(item.last_sell_pnl)}>{formatAmount(item.last_sell_pnl)}</span>
                    </div>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </section>
  );
}

function InfoCell({ label, value, valueClass }: { label: string; value?: string | number | null; valueClass?: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn("mt-0.5 font-medium tabular-nums", valueClass)}>{value ?? "--"}</div>
    </div>
  );
}

function formatTime(value?: string | null) {
  if (!value) return "--";
  const normalized = value.replace("T", " ");
  return normalized.length > 16 ? normalized.slice(0, 16) : normalized;
}

function sourceLabel(source?: string | null) {
  if (source === "manual") return "手动";
  if (source === "quant_screen") return "量化筛选";
  if (source === "simulation_auto") return "自动模拟";
  if (source === "quant_auto") return "量化自动";
  return source || "--";
}
