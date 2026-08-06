import type { HTMLAttributes } from "react";
import { cn } from "../../lib/utils";

const statusStyles: Record<string, string> = {
  running: "bg-amber-200 text-amber-950",
  succeeded: "bg-emerald-700 text-white",
  failed: "bg-red-700 text-white",
  skipped: "bg-slate-300 text-slate-800",
  idle: "bg-slate-200 text-slate-700"
};

export function Badge({ className, ...props }: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn("inline-flex h-7 items-center justify-center rounded-md px-2.5 text-xs font-bold", className)}
      {...props}
    />
  );
}

export function StatusBadge({ status }: { status?: string }) {
  const value = status || "idle";
  return <Badge className={cn(statusStyles[value] || "bg-slate-200 text-slate-700")}>{value}</Badge>;
}
