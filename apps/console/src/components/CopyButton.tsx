import { useEffect, useRef, useState } from "react";
import { Check, Copy, AlertCircle } from "lucide-react";

export function CopyButton({ value, label = "Copy forecast hash" }: { value: string; label?: string }) {
  const [status, setStatus] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => () => clearTimeout(timer.current), []);
  const copy = async () => {
    try { await navigator.clipboard.writeText(value); setStatus("copied"); }
    catch { setStatus("failed"); }
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setStatus("idle"), 2000);
  };
  const title = status === "copied" ? "Hash copied" : status === "failed" ? "Clipboard unavailable" : label;
  return <button onClick={copy} title={title} aria-label={title}>
    {status === "copied" ? <Check size={13} /> : status === "failed" ? <AlertCircle size={13} /> : <Copy size={13} />}
  </button>;
}
