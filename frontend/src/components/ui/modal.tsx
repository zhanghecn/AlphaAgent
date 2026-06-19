import { useEffect, type ReactNode } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

const EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];

/**
 * Minimal modal primitive.
 *
 * 手写浮层模式（fixed inset-0 + 居中 + ESC + 点击遮罩关闭 + stopPropagation），
 * 复用所有 portfolio dialog 的统一 focus/escape/click-out 行为，不引 radix-dialog。
 * 动效改用 framer-motion AnimatePresence：进入 fade+scale，退出补齐（原 animate-fade-in/scale-in 无 exit）。
 */
interface ModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
  className?: string;
}

function Modal({ open, onOpenChange, children, className }: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onOpenChange(false);
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, onOpenChange]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 p-4 backdrop-blur-sm"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          onClick={() => onOpenChange(false)}
        >
          <motion.div
            className={cn(
              "w-full max-w-lg rounded-xl border bg-card text-card-foreground shadow-card-hover",
              className,
            )}
            initial={{ opacity: 0, scale: 0.96, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: 8 }}
            transition={{ duration: 0.22, ease: EASE }}
            onClick={(event) => event.stopPropagation()}
          >
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
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
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onClose}>
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
