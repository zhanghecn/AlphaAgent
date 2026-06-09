/**
 * ConceptTag — 概念标签组件
 *
 * Renders a colored badge for a concept/industry sector.
 * Background color varies by change_pct (rise=red, fall=green, flat=gray).
 * Industry tags get a blue tint to distinguish from concept tags.
 */
import { cn, formatPct } from "@/lib/utils";

export interface ConceptTagProps {
  name: string;
  changePct?: number | null;
  type?: "concept" | "industry";
  /** When true, show a small flame emoji for high-heat items */
  hot?: boolean;
  onClick?: () => void;
  className?: string;
}

export function ConceptTag({
  name,
  changePct,
  type = "concept",
  hot = false,
  onClick,
  className,
}: ConceptTagProps) {
  const isRise = changePct != null && changePct > 0;
  const isFall = changePct != null && changePct < 0;

  const colorClass =
    type === "industry"
      ? "concept-tag-industry"
      : isRise
        ? "concept-tag-rise"
        : isFall
          ? "concept-tag-fall"
          : "concept-tag-flat";

  return (
    <button
      type="button"
      className={cn("concept-tag", colorClass, className)}
      onClick={onClick}
      title={`${name}${changePct != null ? ` ${formatPct(changePct)}` : ""}`}
    >
      <span>{name}</span>
      {changePct != null && (
        <span className="opacity-80">
          {changePct > 0 ? "▲" : changePct < 0 ? "▼" : "–"}
          {Math.abs(changePct).toFixed(1)}%
        </span>
      )}
      {hot && <span>🔥</span>}
    </button>
  );
}
