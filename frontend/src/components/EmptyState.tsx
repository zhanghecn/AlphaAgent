import { Inbox } from "lucide-react";
import { Reveal } from "@/components/motion";

interface EmptyStateProps {
  message?: string;
  description?: string;
}

export function EmptyState({ message = "暂无数据", description }: EmptyStateProps) {
  return (
    <Reveal>
      <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-8 text-center">
        <Inbox className="h-8 w-8 animate-float text-muted-foreground/50" />
        <p className="text-sm font-medium text-muted-foreground">{message}</p>
        {description && (
          <p className="text-xs text-muted-foreground/70">{description}</p>
        )}
      </div>
    </Reveal>
  );
}
