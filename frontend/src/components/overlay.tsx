import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import { useStore } from "../lib/store";
import { cx, IconButton } from "./ui";

export function Modal({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
  width = 560,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  width?: number;
}) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
      if (e.key === "Tab" && panel.current) {
        const focusable = panel.current.querySelectorAll<HTMLElement>(
          "button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex='-1'])",
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/25 p-6 backdrop-blur-[2px] animate-fade-in">
      <div className="absolute inset-0" onClick={onClose} aria-hidden />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className="animate-pop relative flex max-h-[85vh] w-full flex-col rounded-[16px] border border-line bg-surface shadow-pop outline-none"
        style={{ maxWidth: width }}
      >
        <div className="flex items-start justify-between gap-4 border-b border-line px-5 pb-3 pt-4">
          <div className="min-w-0">
            <h2 className="truncate text-[15px] font-semibold">{title}</h2>
            {subtitle && <div className="mt-0.5 text-[12.5px] text-ink-2">{subtitle}</div>}
          </div>
          <IconButton label="Close" onClick={onClose}>
            <X className="size-4" />
          </IconButton>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">{children}</div>
        {footer && <div className="flex items-center justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

const TOAST_ICON = {
  success: <CheckCircle2 className="size-4 text-success" />,
  warning: <AlertTriangle className="size-4 text-warning" />,
  error: <XCircle className="size-4 text-danger" />,
  info: <Info className="size-4 text-accent" />,
};

export function Toasts() {
  const toasts = useStore((s) => s.toasts);
  const dismiss = useStore((s) => s.dismissToast);
  return (
    <div
      className="pointer-events-none fixed right-5 top-4 z-[60] flex w-[360px] flex-col gap-2"
      role="status"
      aria-live="polite"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          className={cx(
            "animate-pop pointer-events-auto flex items-start gap-2.5 rounded-[12px] border border-line bg-surface px-3.5 py-3 text-[12.5px] shadow-pop",
          )}
        >
          <span className="mt-[1px]">{TOAST_ICON[t.kind]}</span>
          <span className="selectable min-w-0 flex-1 text-ink">{t.message}</span>
          <button
            type="button"
            aria-label="Dismiss"
            onClick={() => dismiss(t.id)}
            className="-mr-1 rounded p-0.5 text-ink-3 hover:text-ink"
          >
            <X className="size-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  danger,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  body: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      width={420}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="h-8 rounded-[8px] border border-line-strong bg-surface px-3.5 text-[13px] font-medium hover:bg-surface-2"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => {
              onConfirm();
              onClose();
            }}
            className={cx(
              "h-8 rounded-[8px] px-3.5 text-[13px] font-medium text-white",
              danger ? "bg-danger" : "gradient-accent",
            )}
          >
            {confirmLabel}
          </button>
        </>
      }
    >
      <div className="px-5 py-4 text-[13px] text-ink-2">{body}</div>
    </Modal>
  );
}
