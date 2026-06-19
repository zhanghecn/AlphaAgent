import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle2, Info, X, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Lightweight global toast notifications.
 *
 * 手写（不引 radix-toast）。success 用 brand(indigo)、error 用 destructive，
 * 刻意避开 A 股红涨/绿跌语义，防止与数字配色冲突。
 * 动效改用 framer-motion AnimatePresence：进入 spring 滑入 + exit 淡出收缩，
 * layout 让多条 toast 间位置变化平滑（新 toast 进入时其他自动让位）。
 */
type ToastVariant = "success" | "error" | "default";

interface ToastItem {
  id: number;
  title: string;
  description?: string;
  variant: ToastVariant;
}

interface ToastOptions {
  title: string;
  description?: string;
  variant?: ToastVariant;
  /** Auto-dismiss after ms (default 4000). */
  duration?: number;
}

const ToastContext = createContext<(opts: ToastOptions) => void>(() => {});

let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback(
    (opts: ToastOptions) => {
      const id = nextId++;
      setToasts((prev) => [...prev, { id, title: opts.title, description: opts.description, variant: opts.variant ?? "default" }]);
      const duration = opts.duration ?? 4000;
      if (duration > 0) setTimeout(() => dismiss(id), duration);
    },
    [dismiss],
  );

  return (
    <ToastContext.Provider value={toast}>
      {children}
      {mounted && <Toaster toasts={toasts} onClose={dismiss} />}
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}

function Toaster({ toasts, onClose }: { toasts: ToastItem[]; onClose: (id: number) => void }) {
  return createPortal(
    <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-80 flex-col gap-2">
      <AnimatePresence initial={false}>
        {toasts.map((t) => (
          <ToastCard key={t.id} toast={t} onClose={() => onClose(t.id)} />
        ))}
      </AnimatePresence>
    </div>,
    document.body,
  );
}

function ToastCard({ toast, onClose }: { toast: ToastItem; onClose: () => void }) {
  const icon =
    toast.variant === "success" ? (
      <CheckCircle2 className="text-brand-600 dark:text-brand-400" size={18} />
    ) : toast.variant === "error" ? (
      <XCircle className="text-destructive" size={18} />
    ) : (
      <Info className="text-muted-foreground" size={18} />
    );

  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: 40, scale: 0.96 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: 40, scale: 0.96 }}
      transition={{ type: "spring", stiffness: 350, damping: 30 }}
      className={cn(
        "pointer-events-auto flex items-start gap-2 rounded-lg border bg-card p-3 shadow-card-hover",
        toast.variant === "success" && "border-brand-500/30",
        toast.variant === "error" && "border-destructive/40",
      )}
      role="status"
    >
      <div className="mt-0.5 shrink-0">{icon}</div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{toast.title}</p>
        {toast.description && <p className="mt-0.5 text-xs text-muted-foreground">{toast.description}</p>}
      </div>
      <button type="button" onClick={onClose} className="shrink-0 text-muted-foreground hover:text-foreground">
        <X size={14} />
      </button>
    </motion.div>
  );
}
