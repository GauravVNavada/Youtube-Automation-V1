import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-md text-sm font-semibold outline-none transition-colors focus-visible:ring-2 focus-visible:ring-cyan-700/25 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-cyan-700 text-white hover:bg-cyan-800",
        secondary: "border border-slate-300 bg-white text-slate-900 hover:border-cyan-700 hover:bg-cyan-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:border-cyan-500 dark:hover:bg-slate-800",
        ghost: "text-slate-700 hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800",
        destructive: "border border-red-200 bg-white text-red-700 hover:bg-red-50"
      },
      size: {
        default: "h-10 px-4",
        sm: "h-8 px-3 text-xs",
        icon: "h-9 w-9 p-0"
      }
    },
    defaultVariants: {
      variant: "default",
      size: "default"
    }
  }
);

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  };

export function Button({ className, variant, size, asChild = false, type = "button", ...props }: ButtonProps) {
  const Comp = asChild ? Slot : "button";
  return <Comp type={asChild ? undefined : type} className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}

export { buttonVariants };
