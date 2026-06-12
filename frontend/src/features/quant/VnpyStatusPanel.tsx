import { InfoCell } from "@/components/InfoCell";
import { LoadingState } from "@/components/LoadingState";
import type { VnpyStatus } from "@/api/quant";

export function VnpyStatusPanel({ data, isLoading }: { data?: VnpyStatus; isLoading: boolean }) {
  if (isLoading) return <LoadingState rows={3} />;
  if (!data) return null;
  const missing = data.plugins.filter((item) => item.required_for_a_share && !item.installed);
  const installed = data.plugins.filter((item) => item.installed);
  const statusLabel = data.status === "ready" ? "A股插件就绪" : "本地回测可用";

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
          当前是 AlphaAgent 本地数据和回测链路可用，vn.py 官方 A 股 Datafeed/Gateway 尚未接入。
        </div>
      )}
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
