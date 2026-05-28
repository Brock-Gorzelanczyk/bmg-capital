import { cn } from "@/lib/utils";
import type { InputHTMLAttributes, TextareaHTMLAttributes } from "react";
import { forwardRef } from "react";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  hint?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, hint, className, id, ...props }, ref) => {
    const inputId = id ?? label?.toLowerCase().replace(/\s+/g, "-");
    return (
      <div className="flex flex-col gap-1.5">
        {label && (
          <label htmlFor={inputId} className="text-xs font-medium text-[var(--text-secondary)]">
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          className={cn(
            "h-9 w-full rounded-lg px-3 text-sm",
            "bg-[var(--bg-elevated-2)] text-[var(--text-primary)]",
            "border border-[var(--border-subtle)]",
            "placeholder:text-[var(--text-tertiary)]",
            "transition-colors duration-[150ms]",
            "hover:border-[var(--border-emphasis)]",
            "focus:outline-none focus:border-[var(--accent-positive)] focus:ring-1 focus:ring-[var(--accent-positive)]/40",
            error && "border-[var(--accent-negative)] focus:border-[var(--accent-negative)] focus:ring-[var(--accent-negative)]/40",
            "disabled:opacity-40 disabled:pointer-events-none",
            className
          )}
          {...props}
        />
        {error && <p className="text-xs text-[var(--accent-negative)]">{error}</p>}
        {hint && !error && <p className="text-xs text-[var(--text-tertiary)]">{hint}</p>}
      </div>
    );
  }
);
Input.displayName = "Input";

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
  hint?: string;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ label, error, hint, className, id, ...props }, ref) => {
    const inputId = id ?? label?.toLowerCase().replace(/\s+/g, "-");
    return (
      <div className="flex flex-col gap-1.5">
        {label && (
          <label htmlFor={inputId} className="text-xs font-medium text-[var(--text-secondary)]">
            {label}
          </label>
        )}
        <textarea
          ref={ref}
          id={inputId}
          className={cn(
            "w-full rounded-lg px-3 py-2 text-sm",
            "bg-[var(--bg-elevated-2)] text-[var(--text-primary)]",
            "border border-[var(--border-subtle)]",
            "placeholder:text-[var(--text-tertiary)]",
            "transition-colors duration-[150ms]",
            "hover:border-[var(--border-emphasis)]",
            "focus:outline-none focus:border-[var(--accent-positive)] focus:ring-1 focus:ring-[var(--accent-positive)]/40",
            error && "border-[var(--accent-negative)] focus:border-[var(--accent-negative)] focus:ring-[var(--accent-negative)]/40",
            "disabled:opacity-40 disabled:pointer-events-none resize-none",
            className
          )}
          {...props}
        />
        {error && <p className="text-xs text-[var(--accent-negative)]">{error}</p>}
        {hint && !error && <p className="text-xs text-[var(--text-tertiary)]">{hint}</p>}
      </div>
    );
  }
);
Textarea.displayName = "Textarea";
