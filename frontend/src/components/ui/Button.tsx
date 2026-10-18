import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
  variant?: "primary" | "ghost";
};

export function Button({
  children,
  className,
  variant = "primary",
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex w-full items-center justify-center gap-2 rounded-2xl px-5 py-4 text-base font-medium transition-[transform,background-color,opacity] duration-200 active:scale-[0.99]",
        variant === "primary" &&
          "bg-[var(--ink)] text-fg hover:bg-[#2d2f33] disabled:cursor-not-allowed disabled:opacity-50",
        variant === "ghost" &&
          "bg-transparent text-[var(--muted)] hover:text-foreground",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}
