import { cn } from "@/lib/utils";
import { useState, forwardRef } from "react";
import type { InputHTMLAttributes } from "react";

interface GlowInputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  hint?: string;
}

export const GlowInput = forwardRef<HTMLInputElement, GlowInputProps>(
  ({ label, error, hint, className, id, onFocus, onBlur, style, ...props }, ref) => {
    const [focused, setFocused] = useState(false);
    const inputId = id ?? label?.toLowerCase().replace(/\s+/g, "-");

    return (
      <div className="flex flex-col gap-1.5">
        {label && (
          <label
            htmlFor={inputId}
            className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--bmg-text-label)]"
          >
            {label}
          </label>
        )}
        <div className="relative">
          <input
            ref={ref}
            id={inputId}
            className={cn(
              "w-full bg-transparent text-sm text-[var(--bmg-text)]",
              "border-b pb-1.5 pt-0.5 px-0",
              "placeholder:text-[var(--bmg-text-muted)]",
              "focus:outline-none transition-all duration-200",
              "font-mono tracking-wide",
              error
                ? "border-b-[var(--bmg-red)]"
                : focused
                ? "border-b-[var(--bmg-green)]"
                : "border-b-[var(--bmg-text-muted)]",
              className
            )}
            style={{
              borderBottomColor: error
                ? "var(--bmg-red)"
                : focused
                ? "var(--bmg-green)"
                : "var(--bmg-text-muted)",
              boxShadow: focused && !error
                ? "0 1px 8px var(--bmg-green-glow)"
                : undefined,
              ...style,
            }}
            onFocus={(e) => { setFocused(true); onFocus?.(e); }}
            onBlur={(e) => { setFocused(false); onBlur?.(e); }}
            {...props}
          />
          {focused && !error && (
            <div className="absolute bottom-0 left-0 right-0 h-px overflow-hidden pointer-events-none">
              <div
                className="h-full w-16 bg-gradient-to-r from-transparent via-[var(--bmg-green)]/30 to-transparent"
                style={{ animation: "bmg-scan 1.5s linear infinite" }}
              />
            </div>
          )}
        </div>
        {error && <p className="text-[10px] text-[var(--bmg-red)]">{error}</p>}
        {hint && !error && <p className="text-[10px] text-[var(--bmg-text-muted)]">{hint}</p>}
      </div>
    );
  }
);
GlowInput.displayName = "GlowInput";
