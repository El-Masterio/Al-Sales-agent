/**
 * src/components/ui.tsx
 * =====================
 * Small shared UI primitives used across pages.
 */
"use client";

import clsx from "clsx";
import type { ReactNode } from "react";

export function Panel({
  children,
  className,
  title,
  action,
}: {
  children: ReactNode;
  className?: string;
  title?: string;
  action?: ReactNode;
}) {
  return (
    <section
      className={clsx(
        "rounded-panel border border-ink-600/60 bg-ink-900 shadow-panel",
        className,
      )}
    >
      {title && (
        <header className="flex items-center justify-between border-b border-ink-600/60 px-5 py-3.5">
          <h2 className="font-mono text-xs uppercase tracking-[0.18em] text-mist-400">{title}</h2>
          {action}
        </header>
      )}
      <div className={title ? "p-5" : ""}>{children}</div>
    </section>
  );
}

// ── Lead-status + reply-classification visual language ────────────────────────

const STATUS_STYLES: Record<string, string> = {
  new: "text-mist-300 bg-ink-700",
  researching: "text-amber bg-amber/10",
  ready_to_contact: "text-signal bg-signal/10",
  contacted: "text-mist-200 bg-ink-600",
  interested: "text-signal-glow bg-signal/15",
  meeting_scheduled: "text-signal-glow bg-signal/20",
  not_interested: "text-coral bg-coral/10",
  unsubscribed: "text-coral bg-coral/10",
  closed_won: "text-signal-glow bg-signal/25",
  closed_lost: "text-mist-500 bg-ink-700",
};

export function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_STYLES[status] ?? "text-mist-300 bg-ink-700";
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded px-2 py-0.5 font-mono text-[11px] tracking-wide",
        cls,
      )}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}

const CLASSIFICATION_TONE: Record<string, string> = {
  interested: "text-signal",
  wants_demo: "text-signal",
  needs_pricing: "text-signal",
  positive_general: "text-signal-glow",
  maybe_later: "text-amber",
  question: "text-amber",
  out_of_office: "text-mist-400",
  wrong_person: "text-amber",
  not_interested: "text-coral",
  negative_general: "text-coral",
  unsubscribe_request: "text-coral",
  unclassified: "text-mist-500",
};

export function ClassificationTag({ value }: { value: string }) {
  const tone = CLASSIFICATION_TONE[value] ?? "text-mist-400";
  return (
    <span className={clsx("font-mono text-xs", tone)}>{value.replace(/_/g, " ")}</span>
  );
}

export function Button({
  children,
  onClick,
  variant = "default",
  disabled,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "default" | "signal" | "ghost" | "danger";
  disabled?: boolean;
  type?: "button" | "submit";
}) {
  const styles = {
    default: "bg-ink-700 hover:bg-ink-600 text-mist-100 border border-ink-500/50",
    signal: "bg-signal/15 hover:bg-signal/25 text-signal border border-signal/30",
    ghost: "hover:bg-ink-700 text-mist-300",
    danger: "bg-coral/10 hover:bg-coral/20 text-coral border border-coral/30",
  }[variant];
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        "rounded px-3.5 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40",
        styles,
      )}
    >
      {children}
    </button>
  );
}

export function Spinner() {
  return (
    <div className="flex items-center gap-2 text-mist-500">
      <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-ink-500 border-t-signal" />
      <span className="font-mono text-xs">loading…</span>
    </div>
  );
}

export function EmptyState({ message, action }: { message: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 py-14 text-center">
      <p className="max-w-sm text-sm text-mist-500">{message}</p>
      {action}
    </div>
  );
}
