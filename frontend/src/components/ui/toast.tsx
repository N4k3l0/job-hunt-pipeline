"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { CheckCircle2, AlertCircle, Info, X, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

type ToastVariant = "success" | "error" | "info" | "loading" | "action";

interface BaseToast {
  id: string;
  message: string;
  description?: string;
  variant: ToastVariant;
  duration: number;
}

interface ActionToast extends BaseToast {
  variant: "action";
  actionLabel: string;
  onCommit: () => void | Promise<void>;
  onUndo?: () => void;
}

type ToastItem = BaseToast | ActionToast;

interface ToastContextValue {
  push: (item: Omit<ToastItem, "id">) => string;
  dismiss: (id: string) => void;
  success: (message: string, opts?: { description?: string; duration?: number }) => string;
  error: (message: string, opts?: { description?: string; duration?: number }) => string;
  info: (message: string, opts?: { description?: string; duration?: number }) => string;
  loading: (message: string, opts?: { description?: string }) => string;
  /**
   * Gmail-style "send with undo": shows a toast with a countdown, fires `onCommit`
   * when the timer expires, fires `onUndo` if the user clicks the action.
   */
  action: (opts: {
    message: string;
    description?: string;
    actionLabel?: string;
    duration?: number;
    onCommit: () => void | Promise<void>;
    onUndo?: () => void;
  }) => string;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}

let counter = 0;
const newId = () => `toast-${++counter}-${Date.now()}`;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  // Track per-toast timers + commit handlers so dismiss/undo can cancel/fire them.
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const commits = useRef<Map<string, () => void | Promise<void>>>(new Map());
  const undos = useRef<Map<string, () => void>>(new Map());
  // Track which toasts have already committed so dismissing them doesn't re-fire.
  const committed = useRef<Set<string>>(new Set());

  const dismiss = useCallback((id: string) => {
    const t = timers.current.get(id);
    if (t) clearTimeout(t);
    timers.current.delete(id);
    // Closing a still-pending action toast counts as accepting it (Gmail style).
    const commit = commits.current.get(id);
    if (commit && !committed.current.has(id)) {
      committed.current.add(id);
      void commit();
    }
    commits.current.delete(id);
    undos.current.delete(id);
    setToasts((prev) => prev.filter((x) => x.id !== id));
  }, []);

  const undo = useCallback((id: string) => {
    const t = timers.current.get(id);
    if (t) clearTimeout(t);
    timers.current.delete(id);
    committed.current.add(id); // prevent dismiss from also committing
    const fn = undos.current.get(id);
    commits.current.delete(id);
    undos.current.delete(id);
    if (fn) fn();
    setToasts((prev) => prev.filter((x) => x.id !== id));
  }, []);

  const push = useCallback<ToastContextValue["push"]>((item) => {
    const id = newId();
    const full = { ...item, id } as ToastItem;
    setToasts((prev) => [...prev, full]);
    if (full.variant === "action") {
      const a = full as ActionToast;
      commits.current.set(id, a.onCommit);
      if (a.onUndo) undos.current.set(id, a.onUndo);
      const timer = setTimeout(() => {
        if (!committed.current.has(id)) {
          committed.current.add(id);
          void a.onCommit();
        }
        timers.current.delete(id);
        commits.current.delete(id);
        undos.current.delete(id);
        setToasts((prev) => prev.filter((x) => x.id !== id));
      }, a.duration);
      timers.current.set(id, timer);
    } else if (full.variant !== "loading" && full.duration > 0) {
      const timer = setTimeout(() => {
        timers.current.delete(id);
        setToasts((prev) => prev.filter((x) => x.id !== id));
      }, full.duration);
      timers.current.set(id, timer);
    }
    return id;
  }, []);

  const value = useMemo<ToastContextValue>(
    () => ({
      push,
      dismiss,
      success: (message, opts) =>
        push({ variant: "success", message, description: opts?.description, duration: opts?.duration ?? 3500 }),
      error: (message, opts) =>
        push({ variant: "error", message, description: opts?.description, duration: opts?.duration ?? 5000 }),
      info: (message, opts) =>
        push({ variant: "info", message, description: opts?.description, duration: opts?.duration ?? 3500 }),
      loading: (message, opts) =>
        push({ variant: "loading", message, description: opts?.description, duration: 0 }),
      action: (opts) =>
        push({
          variant: "action",
          message: opts.message,
          description: opts.description,
          actionLabel: opts.actionLabel ?? "Undo",
          duration: opts.duration ?? 5000,
          onCommit: opts.onCommit,
          onUndo: opts.onUndo,
        } as Omit<ActionToast, "id">),
    }),
    [push, dismiss],
  );

  // Cleanup on unmount.
  useEffect(() => () => {
    timers.current.forEach(clearTimeout);
    timers.current.clear();
  }, []);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} onUndo={undo} />
    </ToastContext.Provider>
  );
}

function ToastViewport({
  toasts,
  onDismiss,
  onUndo,
}: {
  toasts: ToastItem[];
  onDismiss: (id: string) => void;
  onUndo: (id: string) => void;
}) {
  return (
    <div
      className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2"
      role="region"
      aria-label="Notifications"
    >
      {toasts.map((t) => (
        <ToastItemView key={t.id} toast={t} onDismiss={onDismiss} onUndo={onUndo} />
      ))}
    </div>
  );
}

function ToastItemView({
  toast,
  onDismiss,
  onUndo,
}: {
  toast: ToastItem;
  onDismiss: (id: string) => void;
  onUndo: (id: string) => void;
}) {
  const isAction = toast.variant === "action";
  const Icon =
    toast.variant === "success" ? CheckCircle2
    : toast.variant === "error" ? AlertCircle
    : toast.variant === "loading" ? Loader2
    : Info;

  const accent =
    toast.variant === "success" ? "text-emerald-400"
    : toast.variant === "error" ? "text-red-400"
    : toast.variant === "loading" ? "text-muted-foreground"
    : toast.variant === "action" ? "text-amber-400"
    : "text-blue-400";

  return (
    <div
      className={cn(
        "pointer-events-auto group relative overflow-hidden rounded-xl border border-white/10 bg-background/95 backdrop-blur-md shadow-lg shadow-black/30",
        "animate-in slide-in-from-bottom-2 fade-in duration-200",
      )}
    >
      <div className="flex items-start gap-3 px-4 py-3">
        <Icon className={cn("h-4 w-4 mt-0.5 shrink-0", accent, toast.variant === "loading" && "animate-spin")} />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium leading-snug">{toast.message}</p>
          {toast.description && (
            <p className="text-xs text-muted-foreground mt-0.5 leading-snug">{toast.description}</p>
          )}
        </div>
        {isAction && (
          <button
            onClick={() => onUndo(toast.id)}
            className="text-xs font-semibold text-amber-400 hover:text-amber-300 px-2 py-1 -my-1 rounded-md hover:bg-amber-500/10 transition-colors"
          >
            {(toast as ActionToast).actionLabel}
          </button>
        )}
        <button
          onClick={() => onDismiss(toast.id)}
          className="text-muted-foreground/40 hover:text-muted-foreground transition-colors -mr-1 -my-0.5 p-1"
          aria-label="Dismiss"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      {isAction && toast.duration > 0 && (
        <CountdownBar duration={toast.duration} />
      )}
    </div>
  );
}

function CountdownBar({ duration }: { duration: number }) {
  return (
    <div className="h-0.5 bg-amber-500/10 overflow-hidden">
      <div
        className="h-full bg-amber-400 origin-left"
        style={{
          animation: `toast-countdown ${duration}ms linear forwards`,
        }}
      />
      <style>{`
        @keyframes toast-countdown {
          from { transform: scaleX(1); }
          to { transform: scaleX(0); }
        }
      `}</style>
    </div>
  );
}
