import { LayoutGrid, Swords, Undo2 } from "lucide-react";
import { useSearchParams } from "react-router-dom";

import { cn } from "@/lib/utils";
import { FanbaoPage } from "@/pages/FanbaoPage";
import { HighRelayPage } from "@/pages/HighRelayPage";
import { ShortTermOverview } from "@/pages/ShortTermOverview";

type ResearchTab = "overview" | "high-relay" | "fanbao";

const RESEARCH_TABS = [
  { value: "overview", label: "主线总览", icon: LayoutGrid },
  { value: "high-relay", label: "高位接力", icon: Swords },
  { value: "fanbao", label: "断板反包", icon: Undo2 },
] as const;

// 主线三线的子页签深链值(?view=quiz 总览答题按钮直达)
const LINE_VIEWS: Partial<Record<ResearchTab, string[]>> = {
  "high-relay": ["live", "quiz", "backtest", "ledger", "guide"],
  fanbao: ["live", "quiz", "backtest", "ledger", "guide"],
};

export function ShortTermResearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = searchParams.get("research");
  // 精华化(2026-10-02 终版):只留 hpr+fbb 双主线;其余旧书签一律回落总览
  // 一律回落主线总览,不 404。
  const activeTab: ResearchTab =
    raw === "high-relay" || raw === "fanbao" ? (raw as ResearchTab) : "overview";

  const applyParams = (tab: ResearchTab, nextView?: string) => {
    const next = new URLSearchParams(searchParams);
    if (tab === "overview") next.delete("research");
    else next.set("research", tab);
    const allowed = LINE_VIEWS[tab];
    if (nextView && allowed?.includes(nextView)) next.set("view", nextView);
    else next.delete("view");
    setSearchParams(next, { replace: true });
  };

  const panel =
    activeTab === "overview" ? (
      <ShortTermOverview onSelect={(research, view) => applyParams(research as ResearchTab, view)} />
    ) : activeTab === "high-relay" ? (
      <HighRelayPage />
    ) : (
      <FanbaoPage />
    );

  return (
    <div className="min-w-0">
      <nav className="mb-3 flex h-11 items-end gap-6 overflow-x-auto border-b" role="tablist" aria-label="短线研究类型">
        {RESEARCH_TABS.map((tab) => {
          const Icon = tab.icon;
          const active = activeTab === tab.value;
          return (
            <button
              key={tab.value}
              id={`research-tab-${tab.value}`}
              type="button"
              role="tab"
              aria-selected={active}
              aria-controls={`research-panel-${tab.value}`}
              className={cn(
                "flex h-11 shrink-0 items-center gap-2 border-b-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                active
                  ? "border-primary font-semibold text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
              onClick={() => applyParams(tab.value)}
            >
              <Icon size={15} />
              {tab.label}
            </button>
          );
        })}
      </nav>
      <div
        id={`research-panel-${activeTab}`}
        role="tabpanel"
        aria-labelledby={`research-tab-${activeTab}`}
      >
        {panel}
      </div>
    </div>
  );
}
