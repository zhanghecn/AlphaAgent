import { useQuery } from "@tanstack/react-query";
import { fetchReady, fetchDataStatus } from "@/api/dataStatus";
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
import { CheckCircle2, XCircle, HelpCircle } from "lucide-react";
import type { DataSourceStatus, ReadyStatus } from "@/api/types";

export function DataSourceStatusTable({ compact = false }: { compact?: boolean }) {
  const readyQuery = useQuery({
    queryKey: ["ready"],
    queryFn: fetchReady,
  });

  const statusQuery = useQuery({
    queryKey: ["data-status"],
    queryFn: fetchDataStatus,
  });

  if (readyQuery.isLoading) return <LoadingState rows={6} />;
  if (readyQuery.isError)
    return (
      <ErrorState
        message={readyQuery.error instanceof Error ? readyQuery.error.message : "数据状态加载失败"}
        onRetry={() => readyQuery.refetch()}
      />
    );

  const ready = readyQuery.data as ReadyStatus;
  const status = statusQuery.data as Record<string, unknown> | null;
  const dataSources = status?.data_sources as DataSourceStatus[] | undefined;
  const storage = (ready.storage ?? status?.storage ?? []) as DataSourceStatus[];
  const coverage = (ready.coverage ?? status?.coverage) as Record<string, unknown> | undefined;
  const tables = (coverage?.tables ?? status?.tables ?? {}) as Record<string, { rows?: number; stocks?: number; latest_trade_date?: string; updated_at?: string }>;
  const notes = status?.notes as string[] | undefined;

  if (compact) {
    return (
      <div className="grid gap-3 md:grid-cols-3">
        <StatusCard label="API" value={ready.status} />
        <StatusCard label="PostgreSQL" value={ready.postgres ?? ready.persistence ?? "unknown"} />
        <StatusCard label="Redis" value={ready.redis ?? ready.cache ?? "unknown"} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* System Status */}
      <section>
        <h3 className="text-sm font-medium text-muted-foreground mb-3">系统状态</h3>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatusCard label="整体状态" value={ready.status} />
          <StatusCard label="持久化" value={ready.persistence ?? ready.postgres ?? "not_required"} />
          <StatusCard label="缓存" value={ready.cache ?? ready.redis ?? "not_required"} />
          <StatusCard
            label="市场数据源"
            value={ready.market_data?.some((s) => s.ok) ? "available" : "unavailable"}
          />
        </div>
      </section>

      {storage.length > 0 && (
        <section>
          <h3 className="text-sm font-medium text-muted-foreground mb-3">存储与缓存</h3>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>组件</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>信息</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {storage.map((item) => (
                <TableRow key={item.name}>
                  <TableCell className="font-mono text-sm">{item.name}</TableCell>
                  <TableCell>
                    <StatusIcon ok={item.ok} />
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">{item.message}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </section>
      )}

      {Object.keys(tables).length > 0 && (
        <section>
          <h3 className="text-sm font-medium text-muted-foreground mb-3">本地表覆盖率</h3>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {Object.entries(tables).map(([name, table]) => (
              <div key={name} className="rounded-lg border p-3">
                <p className="font-mono text-xs text-muted-foreground">{name}</p>
                <p className="mt-2 font-display text-xl font-semibold tabular-nums">{table.rows ?? 0}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {table.latest_trade_date ? `最新 ${table.latest_trade_date}` : table.stocks != null ? `${table.stocks} 只股票` : table.updated_at ? "已同步" : "--"}
                </p>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Market Data Sources */}
      <section>
        <h3 className="text-sm font-medium text-muted-foreground mb-3">行情数据源</h3>
        {ready.market_data && ready.market_data.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>数据源</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>信息</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {ready.market_data.map((source) => (
                <TableRow key={source.name}>
                  <TableCell className="font-mono text-sm">{source.name}</TableCell>
                  <TableCell>
                    <StatusIcon ok={source.ok} />
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {source.message}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <p className="text-sm text-muted-foreground">暂无数据源信息</p>
        )}
      </section>

      {/* Detailed Data Sources (from /data/status) */}
      {dataSources && dataSources.length > 0 && (
        <section>
          <h3 className="text-sm font-medium text-muted-foreground mb-3">数据源详情</h3>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>名称</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>信息</TableHead>
                <TableHead>检查时间</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {dataSources.map((ds) => (
                <TableRow key={ds.name}>
                  <TableCell className="font-mono text-sm">{ds.name}</TableCell>
                  <TableCell>
                    <StatusIcon ok={ds.ok} />
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">{ds.message}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {ds.checked_at
                      ? new Date(ds.checked_at).toLocaleString("zh-CN")
                      : "--"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </section>
      )}

      {/* Notes */}
      {notes && notes.length > 0 && (
        <section>
          <h3 className="text-sm font-medium text-muted-foreground mb-2">备注</h3>
          <ul className="space-y-1">
            {notes.map((note, i) => (
              <li key={i} className="text-xs text-muted-foreground">
                {note}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function StatusCard({ label, value }: { label: string; value: string }) {
  const isOk = value === "ready" || value === "ok" || value === "available" || value === "not_required";
  const isPending = value === "pending";
  return (
    <div className="rounded-lg border p-3 space-y-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="flex items-center gap-2">
        <StatusIcon ok={isOk} pending={isPending} />
        <span className="text-sm font-medium">{value}</span>
      </div>
    </div>
  );
}

function StatusIcon({ ok, pending }: { ok: boolean; pending?: boolean }) {
  if (ok) return <CheckCircle2 size={16} className="text-green-500" />;
  if (pending) return <HelpCircle size={16} className="text-yellow-500" />;
  return <XCircle size={16} className="text-red-500" />;
}
