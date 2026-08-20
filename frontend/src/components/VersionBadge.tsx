import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, ExternalLink, RefreshCw, RotateCcw } from "lucide-react";
import { checkUpdates, performUpdate, restartService } from "@/api/system";
import { cn } from "@/lib/utils";

/**
 * 管理员版本菜单：显示当前版本，有新版黄点高亮；点击下拉
 * 重新检查 / 立即更新 / 重启 / 查看发布说明。
 * 触发更新或重启后，api 容器会被重建，进入 busy 态轮询恢复。
 */
export function canManageSystem(isAdmin: boolean, isRelease: boolean): boolean {
  return isAdmin && isRelease;
}

export function VersionBadge({ isAdmin }: { isAdmin: boolean }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [busyMsg, setBusyMsg] = useState("");
  const menuRef = useRef<HTMLDivElement>(null);

  const { data, isFetching, refetch } = useQuery({
    queryKey: ["systemVersion"],
    queryFn: () => checkUpdates(),
    enabled: isAdmin,
    staleTime: 4 * 60_000,
    refetchInterval: 5 * 60_000,
  });

  const current = data?.current ?? "…";
  const hasUpdate = data?.has_update ?? false;
  const isRelease = data?.build_type === "release";
  const releaseUrl = data?.release_info?.html_url;
  const canManage = canManageSystem(isAdmin, isRelease);

  // 点击外部关闭菜单
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // busy：更新/重启后 api 会被重建，轮询直到恢复
  useEffect(() => {
    if (!busy) return;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      attempts += 1;
      try {
        await checkUpdates(true);
        qc.invalidateQueries({ queryKey: ["systemVersion"] });
        setBusy(false);
      } catch {
        if (attempts < 40) {
          timer = setTimeout(tick, 3000);
        } else {
          setBusy(false);
        }
      }
    };
    timer = setTimeout(tick, 6000);
    return () => clearTimeout(timer);
  }, [busy, qc]);

  const updateMut = useMutation({
    mutationFn: performUpdate,
    onSuccess: () => {
      setOpen(false);
      setBusyMsg("更新中：拉取镜像并重启…");
      setBusy(true);
    },
  });
  const restartMut = useMutation({
    mutationFn: restartService,
    onSuccess: () => {
      setOpen(false);
      setBusyMsg("重启中…");
      setBusy(true);
    },
  });

  if (!isAdmin) return null;

  if (busy) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground">
        <RefreshCw size={10} className="animate-spin" />
        {busyMsg}
      </span>
    );
  }

  return (
    <div className="relative" ref={menuRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 rounded text-[10px] font-medium text-muted-foreground transition-colors hover:text-foreground"
        title={hasUpdate ? `有新版本 ${data?.latest}` : "当前版本"}
      >
        <span className="tabular-nums">{current}</span>
        {hasUpdate && (
          <span
            className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-yellow-500"
            title="有新版本可用"
          />
        )}
        <RefreshCw size={9} className={cn(isFetching && "animate-spin")} />
      </button>
      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-56 rounded-md border bg-popover p-1 text-xs shadow-md">
          <div className="px-2 py-1.5 text-muted-foreground">
            当前 <span className="font-medium tabular-nums text-foreground">{current}</span>
            {data?.latest && (
              <div>
                最新{" "}
                <span className={cn("font-medium tabular-nums", hasUpdate && "text-yellow-600")}>
                  {data.latest}
                </span>
              </div>
            )}
            {!isRelease && (
              <div className="mt-0.5 text-[10px] text-amber-600">源码构建，请用 git pull 更新</div>
            )}
          </div>
          <button
            type="button"
            onClick={() => refetch()}
            disabled={isFetching}
            className="flex w-full items-center gap-2 rounded px-2 py-1.5 transition-colors hover:bg-muted disabled:opacity-40"
          >
            <RefreshCw size={12} className={isFetching ? "animate-spin" : ""} /> 重新检查
          </button>
          {canManage && (
            <button
              type="button"
              onClick={() => updateMut.mutate()}
              disabled={updateMut.isPending || !hasUpdate}
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 transition-colors hover:bg-muted disabled:opacity-40"
            >
              <Download size={12} /> 立即更新
            </button>
          )}
          {canManage && (
            <button
              type="button"
              onClick={() => restartMut.mutate()}
              disabled={restartMut.isPending}
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 transition-colors hover:bg-muted disabled:opacity-40"
            >
              <RotateCcw size={12} /> 重启服务
            </button>
          )}
          {releaseUrl && (
            <a
              href={releaseUrl}
              target="_blank"
              rel="noreferrer"
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 transition-colors hover:bg-muted"
            >
              <ExternalLink size={12} /> 查看发布说明
            </a>
          )}
          {updateMut.error && (
            <div className="px-2 py-1 text-[10px] text-red-600">
              {(updateMut.error as Error).message}
            </div>
          )}
          {data?.error && <div className="px-2 py-1 text-[10px] text-amber-600">{data.error}</div>}
        </div>
      )}
    </div>
  );
}
