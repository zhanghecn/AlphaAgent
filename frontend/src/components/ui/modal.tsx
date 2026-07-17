import { useEffect, type ReactNode } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

/**
 * Minimal modal primitive.
 *
 * Reuses the hand-written overlay pattern (fixed inset-0 + centered + ESC +
 * click-outside-to-close + stopPropagation) that AddToGroupDialog used, so
 * every portfolio dialog shares one focus/escape/click-out behavior without
 * pulling in radix-dialog. Uses design-system tokens (bg-card, shadow-card-
 * hover, animate-fade-in / animate-scale-in) and adapts to dark mode.
 */
interface ModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
  className?: string;
  ariaLabel?: string;
}

function Modal({ open, onOpenChange, children, className, ariaLabel }: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onOpenChange(false);
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, onOpenChange]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 p-4 backdrop-blur-sm animate-fade-in"
      onClick={() => onOpenChange(false)}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
        className={cn(
          "w-full max-w-lg rounded-xl border bg-card text-card-foreground shadow-card-hover animate-scale-in",
          className,
        )}
        onClick={(event) => event.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

function ModalHeader({
  title,
  onClose,
  className,
}: {
  title: ReactNode;
  onClose?: () => void;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center justify-between border-b px-5 py-3", className)}>
      <h2 className="font-display text-base font-semibold tracking-tight">{title}</h2>
      {onClose && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          aria-label="关闭"
          title="关闭"
          onClick={onClose}
        >
          <X className="h-4 w-4" />
        </Button>
      )}
    </div>
  );
}

function ModalBody({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("px-5 py-4", className)}>{children}</div>;
}

function ModalFooter({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-center justify-end gap-2 border-t px-5 py-3", className)}>
      {children}
    </div>
  );
}

export { Modal, ModalHeader, ModalBody, ModalFooter };
