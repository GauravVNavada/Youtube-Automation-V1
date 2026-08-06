import * as LabelPrimitive from "@radix-ui/react-label";
import type { ComponentPropsWithoutRef } from "react";
import { cn } from "../../lib/utils";

export function Label({ className, ...props }: ComponentPropsWithoutRef<typeof LabelPrimitive.Root>) {
  return <LabelPrimitive.Root className={cn("text-xs font-semibold text-slate-600 dark:text-slate-300", className)} {...props} />;
}

export function Field({ className, ...props }: ComponentPropsWithoutRef<"label">) {
  return <label className={cn("grid min-w-0 gap-1.5", className)} {...props} />;
}
