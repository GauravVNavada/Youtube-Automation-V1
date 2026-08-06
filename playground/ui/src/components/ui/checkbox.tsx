import * as CheckboxPrimitive from "@radix-ui/react-checkbox";
import { Check } from "lucide-react";
import type { ComponentPropsWithoutRef } from "react";
import { cn } from "../../lib/utils";

export function Checkbox({ className, ...props }: ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>) {
  return (
    <CheckboxPrimitive.Root
      className={cn(
        "grid h-4 w-4 place-items-center rounded border border-slate-300 bg-white outline-none transition focus-visible:ring-2 focus-visible:ring-cyan-700/25 data-[state=checked]:border-cyan-700 data-[state=checked]:bg-cyan-700 data-[state=checked]:text-white",
        className
      )}
      {...props}
    >
      <CheckboxPrimitive.Indicator>
        <Check className="h-3 w-3" />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
}
