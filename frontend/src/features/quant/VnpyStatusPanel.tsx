import { InfoCell } from "@/components/InfoCell";
import { LoadingState } from "@/components/LoadingState";
import type { VnpyStatus } from "@/api/quant";

export function VnpyStatusPanel({ data, isLoading }: { data?: VnpyStatus; isLoading: boolean }) {
  if (isLoading) return <LoadingState rows={3} />;
  if (!data) return null;
  const missing = data.plugins.filter((item) => item.required_for_a_share && !item.installed);
  const installed = data.plugins.filter((item) => item.installed);
  const statusLabel = data.status === "ready" ? "A股插件就绪" : "本地研究就绪，A股接入待配置";
  const capabilities = data.capabilities ?? {};
  const checks = [
    { label: "vn.py core", ready: installed.some((item) => item.module === "vnpy"), next: "已安装，可作为对象模型和本地适配基础。" },
    { label: "本地日线回测", ready: Boolean(capabilities.alphaagent_local_daily_backtest), next: "同步股票清单和日线后可用。" },
    { label: "14:30分钟快照", ready: Boolean(capabilities.alphaagent_local_minute_tail_entry), next: "用数据同步的回测缺口模式按回测 ID 补 1m 快照。" },
    { label: "A股 Datafeed", ready: Boolean(capabilities.vnpy_a_share_datafeed), next: "安装并配置 vnpy_xt、vnpy_rqdata 或 vnpy_tushare。" },
    { label: "A股 Gateway", ready: Boolean(capabilities.vnpy_a_share_gateway), next: "安装并配置 vnpy_xtp、vnpy_tora、vnpy_ost 或 vnpy_emt。" },
  ];

  return (
    <section className="rounded-lg border p-4 text-sm">
      <h2 className="text-sm font-semibold">vn.py 集成</h2>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <InfoCell label="状态" value={statusLabel} />
        <InfoCell label="已安装插件" value={`${installed.length} 个`} />
        <InfoCell label="GUI Gateway" value={data.launcher.registered_gateways.join(", ")} />
        <InfoCell label="A股插件缺口" value={`${missing.length} 项`} />
      </div>
      {data.status !== "ready" && (
        <div className="mt-3 rounded-md border px-3 py-2 text-xs text-muted-foreground">
          当前 AlphaAgent 本地研究链路可用；vn.py 官方 A 股 Datafeed/Gateway 尚未接入，不能按实盘 A 股能力理解。
        </div>
      )}
      <div className="mt-3 overflow-hidden rounded-md border">
        {checks.map((item) => (
          <div key={item.label} className="grid grid-cols-[120px_72px_minmax(0,1fr)] gap-2 border-b px-3 py-2 last:border-b-0">
            <div className="font-medium">{item.label}</div>
            <div className={item.ready ? "text-rise" : "text-muted-foreground"}>{item.ready ? "可用" : "待配置"}</div>
            <div className="text-xs text-muted-foreground">{item.next}</div>
          </div>
        ))}
      </div>
      {missing.length > 0 && (
        <div className="mt-3 border-t pt-3">
          <div className="text-xs text-muted-foreground">待安装/配置</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {missing.slice(0, 8).map((item) => (
              <span key={item.module} className="rounded-md border px-2 py-1 text-xs text-muted-foreground">
                {item.module}
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
