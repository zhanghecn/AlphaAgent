import { FlaskConical, Flame, Rocket } from "lucide-react";
import { useSearchParams } from "react-router-dom";

import { cn } from "@/lib/utils";
import { LimitUpPage } from "@/pages/LimitUpPage";
import { FirstBoardLeaderPage } from "@/pages/FirstBoardLeaderPage";
import { LowSuctionPage } from "@/pages/LowSuctionPage";

type ResearchTab = "limit-up" | "first-board-leader" | "low-suction";

const RESEARCH_TABS = [
  { value: "limit-up", label: "打板研究", icon: Flame },
  { value: "first-board-leader", label: "潜龙首板", icon: Rocket },
  { value: "low-suction", label: "低吸", icon: FlaskConical },
] as const;

export function ShortTermResearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = searchParams.get("research");
  // 旧书签（reverse-wrap / pullback-study）统一归入低吸
  const activeTab: ResearchTab = raw === "first-board-leader"
    ? "first-board-leader"
    : raw === "low-suction" || raw === "reverse-wrap" || raw === "pullback-study"
      ? "low-suction"
      : "limit-up";

  const selectTab = (tab: ResearchTab) => {
    const next = new URLSearchParams(searchParams);
    if (tab === "limit-up") next.delete("research");
    else next.set("research", tab);
    setSearchParams(next, { replace: true });
  };

  const panel = activeTab === "limit-up"
    ? <LimitUpPage />
    : activeTab === "first-board-leader"
      ? <FirstBoardLeaderPage />
      : <LowSuctionPage />;

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
              onClick={() => selectTab(tab.value)}
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
