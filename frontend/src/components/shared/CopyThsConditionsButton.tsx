import { useState } from "react";
import { Check, ClipboardCopy } from "lucide-react";

import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

async function copyText(value: string): Promise<boolean> {
  if (navigator.clipboard?.writeText && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch {
      // HTTP 环境或浏览器权限拒绝时走兼容方案
    }
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  return copied;
}

/** 「复制同花顺条件」按钮:盘前池条件串一键复制,粘贴进同花顺动态板块。 */
export function CopyThsConditionsButton({
  conditions,
  className,
  label = "复制同花顺条件",
  copiedLabel = "已复制",
}: {
  conditions: string;
  className?: string;
  label?: string;
  copiedLabel?: string;
}) {
  const toast = useToast();
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      const ok = await copyText(conditions);
      if (!ok) throw new Error("copy failed");
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2_000);
      toast({
        title: "同花顺条件已复制",
        description: "打开同花顺「动态板块」,粘贴到条件框即可建池",
        variant: "success",
      });
    } catch {
      toast({
        title: "复制失败",
        description: conditions,
        duration: 8_000,
      });
    }
  };

  return (
    <button
      type="button"
      onClick={() => void handleCopy()}
      className={cn(
        "inline-flex h-8 items-center gap-1.5 rounded-md border border-primary/40 px-3 text-xs font-medium text-primary hover:bg-primary/10",
        className,
      )}
      aria-label="复制同花顺动态板块条件"
    >
      {copied ? <Check size={13} /> : <ClipboardCopy size={13} />}
      {copied ? copiedLabel : label}
    </button>
  );
}
