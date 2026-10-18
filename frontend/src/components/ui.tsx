// Small, consistent building blocks: buttons, toggles, selects, segmented controls, progress.

import type { ButtonHTMLAttributes, ReactNode } from "react";
import { forwardRef, useId } from "react";
import { ChevronDown, Loader2 } from "lucide-react";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "sm" | "md" | "lg";
  icon?: ReactNode;
  busy?: boolean;
}

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "gradient-accent text-white shadow-[0_1px_2px_rgb(0_0_0/0.18),inset_0_1px_0_rgb(255_255_255/0.18)] hover:brightness-[1.06] active:brightness-95 disabled:opacity-45 disabled:hover:brightness-100",
  secondary:
    "bg-surface text-ink border border-line-strong shadow-[0_1px_1px_rgb(0_0_0/0.04)] hover:bg-surface-2 active:bg-surface-3 disabled:opacity-50",
  ghost: "text-ink-2 hover:bg-surface-3 hover:text-ink active:bg-line disabled:opacity-40",
  danger: "bg-danger text-white hover:brightness-105 active:brightness-95 disabled:opacity-50",
};

const SIZES = {
  sm: "h-7 px-2.5 text-[12px] gap-1.5 rounded-[7px]",
  md: "h-8 px-3.5 text-[13px] gap-2 rounded-[8px]",
  lg: "h-10 px-5 text-[14px] gap-2 rounded-[10px] font-semibold",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", icon, busy, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      disabled={disabled || busy}
      className={cx(
        "inline-flex items-center justify-center whitespace-nowrap font-medium transition-[background,filter,box-shadow,opacity] duration-150 select-none",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    >
      {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
});

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
  tone?: "default" | "danger" | "accent";
}

export function IconButton({ label, tone = "default", className, children, ...rest }: IconButtonProps) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={cx(
        "inline-flex size-7 items-center justify-center rounded-[7px] transition-colors duration-150 disabled:opacity-35",
        tone === "danger"
          ? "text-ink-3 hover:bg-danger-soft hover:text-danger"
          : tone === "accent"
            ? "text-accent-ink hover:bg-accent-soft"
            : "text-ink-3 hover:bg-surface-3 hover:text-ink",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx(
        "relative inline-flex h-[22px] w-[38px] shrink-0 items-center rounded-full transition-colors duration-200 disabled:opacity-40",
        checked ? "bg-accent" : "bg-line-strong",
      )}
    >
      <span
        className={cx(
          "inline-block size-[18px] rounded-full bg-white shadow-[0_1px_3px_rgb(0_0_0/0.25)] transition-transform duration-200",
          checked ? "translate-x-[18px]" : "translate-x-[2px]",
        )}
      />
    </button>
  );
}

export function Select<T extends string>({
  value,
  onChange,
  options,
  label,
  className,
  disabled,
}: {
  value: T;
  onChange: (value: T) => void;
  options: { value: T; label: string }[];
  label: string;
  className?: string;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className={cx("relative inline-flex", className)}>
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <select
        id={id}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value as T)}
        className="h-8 w-full appearance-none rounded-[8px] border border-line-strong bg-surface pl-3 pr-8 text-[13px] text-ink shadow-[0_1px_1px_rgb(0_0_0/0.04)] outline-none transition-colors hover:bg-surface-2 focus-visible:outline-[3px] focus-visible:outline-[var(--focus)] disabled:opacity-50"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 size-3.5 -translate-y-1/2 text-ink-3" />
    </div>
  );
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  size = "md",
}: {
  value: T;
  onChange: (value: T) => void;
  options: { value: T; label: string; count?: number }[];
  label: string;
  size?: "sm" | "md";
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="inline-flex rounded-[9px] bg-surface-3 p-[3px] shadow-[inset_0_0_0_1px_var(--line)]"
    >
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(o.value)}
            className={cx(
              "inline-flex items-center gap-1.5 rounded-[7px] font-medium transition-all duration-150",
              size === "sm" ? "h-6 px-2.5 text-[12px]" : "h-7 px-3 text-[12.5px]",
              active
                ? "bg-surface text-ink shadow-[0_1px_2px_rgb(0_0_0/0.12),0_0_0_0.5px_var(--line)]"
                : "text-ink-2 hover:text-ink",
            )}
          >
            {o.label}
            {o.count != null && o.count > 0 && (
              <span className={cx("tabular-nums text-[11px]", active ? "text-ink-2" : "text-ink-3")}>
                {o.count.toLocaleString()}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export function ProgressBar({
  value,
  tone = "accent",
  indeterminate,
  className,
  label,
}: {
  value: number | null;
  tone?: "accent" | "success" | "danger" | "muted" | "warning";
  indeterminate?: boolean;
  className?: string;
  label?: string;
}) {
  const pct = value == null ? 0 : Math.max(0, Math.min(1, value)) * 100;
  const color = {
    accent: "gradient-accent",
    success: "bg-success",
    danger: "bg-danger",
    muted: "bg-ink-3",
    warning: "bg-warning",
  }[tone];
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={indeterminate || value == null ? undefined : Math.round(pct)}
      className={cx(
        "relative h-[5px] w-full overflow-hidden rounded-full bg-track",
        indeterminate && "indeterminate",
        className,
      )}
    >
      {!indeterminate && (
        <div
          className={cx("h-full rounded-full transition-[width] duration-300 ease-out", color)}
          style={{ width: `${pct}%` }}
        />
      )}
    </div>
  );
}

export function Checkbox({
  checked,
  indeterminate,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  indeterminate?: boolean;
  onChange: (value: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={indeterminate ? "mixed" : checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx(
        "inline-flex size-[17px] shrink-0 items-center justify-center rounded-[5px] border transition-colors duration-150 disabled:opacity-35",
        checked || indeterminate
          ? "border-transparent bg-accent text-white"
          : "border-line-strong bg-surface hover:border-ink-3",
      )}
    >
      {indeterminate ? (
        <span className="h-[2px] w-2 rounded bg-white" />
      ) : checked ? (
        <svg viewBox="0 0 12 12" className="size-3" aria-hidden>
          <path d="M2.5 6.2 4.9 8.5 9.5 3.6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      ) : null}
    </button>
  );
}

export function Badge({
  children,
  tone = "neutral",
  className,
}: {
  children: ReactNode;
  tone?: "neutral" | "accent" | "success" | "warning" | "danger";
  className?: string;
}) {
  const tones = {
    neutral: "bg-surface-3 text-ink-2",
    accent: "bg-accent-soft text-accent-ink",
    success: "bg-success-soft text-success",
    warning: "bg-warning-soft text-warning",
    danger: "bg-danger-soft text-danger",
  };
  return (
    <span
      className={cx(
        "inline-flex h-[19px] items-center gap-1 rounded-full px-2 text-[11px] font-medium whitespace-nowrap",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="flex items-end justify-between gap-4 px-8 pb-4 pt-7">
      <div className="min-w-0">
        <h1 className="font-display text-[22px] font-semibold tracking-[-0.02em] text-ink">{title}</h1>
        {subtitle && <p className="mt-0.5 text-[13px] text-ink-2">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  );
}

export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon: ReactNode;
  title: string;
  body: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="animate-fade-in flex flex-col items-center justify-center px-8 py-16 text-center">
      <div className="mb-4 flex size-14 items-center justify-center rounded-2xl bg-surface-3 text-ink-3 shadow-[inset_0_0_0_1px_var(--line)]">
        {icon}
      </div>
      <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
      <p className="mt-1 max-w-[380px] text-[13px] text-ink-2">{body}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
