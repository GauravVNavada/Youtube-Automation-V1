import * as TabsPrimitive from "@radix-ui/react-tabs";
import type { ComponentPropsWithoutRef } from "react";
import { cn } from "../../lib/utils";

export const Tabs = TabsPrimitive.Root;

export function TabsList({ className, ...props }: ComponentPropsWithoutRef<typeof TabsPrimitive.List>) {
  return <TabsPrimitive.List className={cn("flex gap-1 overflow-x-auto rounded-md bg-slate-100 p-1 dark:bg-slate-900", className)} {...props} />;
}

export function TabsTrigger({ className, ...props }: ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "inline-flex h-8 min-w-20 items-center justify-center gap-1.5 rounded-sm px-3 text-xs font-semibold text-slate-600 transition data-[state=active]:bg-white data-[state=active]:text-cyan-800 data-[state=active]:shadow-sm dark:text-slate-300 dark:data-[state=active]:bg-slate-800 dark:data-[state=active]:text-cyan-200",
        className
      )}
      {...props}
    />
  );
}

export function TabsContent({ className, ...props }: ComponentPropsWithoutRef<typeof TabsPrimitive.Content>) {
  return <TabsPrimitive.Content className={cn("mt-4 outline-none", className)} {...props} />;
}
