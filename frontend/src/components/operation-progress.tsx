"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

export interface OperationStage {
  /** Short imperative label shown when the stage is active. */
  label: string;
  /** Budgeted duration in milliseconds. Used to drive the progress bar
   *  and to advance the active stage. The bar overruns gracefully if
   *  the real operation takes longer than the budget. */
  durationMs: number;
  /** Optional one-liner shown below the bar while this stage is active. */
  tip?: string;
}

interface OperationProgressProps {
  stages: OperationStage[];
  /** Driven by the caller — flip true when the operation starts,
   *  false when it ends. Component resets internal state on the falling edge. */
  active: boolean;
  /** Optional heading shown at the top of the card. */
  title?: string;
  /** Optional small description under the heading. */
  description?: string;
  /** Override the container className if you need to embed this in a
   *  surface that doesn't want the default amber wash. */
  className?: string;
}

/**
 * Drop-in progress panel for long-running operations.
 *
 * Same visual language as the apply-link resolver popup (which users
 * already get) — stage list with check + active-dot states, smooth
 * ease-out cubic progress bar, live elapsed counter, rotating tip text.
 * Time-based (not real server progress) so it works for any operation
 * without backend instrumentation — each stage has a budgeted duration
 * and the bar advances against that budget. If the operation runs
 * over, the bar creeps from 95% toward 99% so it never looks frozen.
 *
 * Honest copy: stages reflect the actual backend pipeline so the
 * labels are real, not vibes.
 */
export function OperationProgress({
  stages,
  active,
  title,
  description,
  className,
}: OperationProgressProps) {
  const [pct, setPct] = useState(0);
  const [stageIdx, setStageIdx] = useState(0);
  const [elapsedS, setElapsedS] = useState(0);
  const [tipVisible, setTipVisible] = useState(true);
  const startRef = useRef<number | null>(null);
  const rafRef = useRef<number | null>(null);
  const lastStageRef = useRef(0);

  useEffect(() => {
    if (!active) {
      // Reset on each new run.
      setPct(0);
      setStageIdx(0);
      setElapsedS(0);
      startRef.current = null;
      lastStageRef.current = 0;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      return;
    }

    startRef.current = performance.now();
    const totalDuration = stages.reduce((sum, s) => sum + s.durationMs, 0) || 1;
    const cap = 95; // last 5% reserved so we never claim "100%" while still running

    const tick = (now: number) => {
      if (!startRef.current) return;
      const elapsedMs = now - startRef.current;
      setElapsedS(elapsedMs / 1000);

      // Active stage: walk the cumulative durations until we exceed elapsed.
      let cumulative = 0;
      let current = stages.length - 1;
      for (let i = 0; i < stages.length; i++) {
        cumulative += stages[i].durationMs;
        if (elapsedMs < cumulative) {
          current = i;
          break;
        }
      }
      if (current !== lastStageRef.current) {
        // Cross-fade the tip when the stage flips.
        setTipVisible(false);
        setTimeout(() => {
          setStageIdx(current);
          setTipVisible(true);
        }, 200);
        lastStageRef.current = current;
      }

      // Progress: ease-out cubic against the full budget, capped at 95%.
      const t = Math.min(1, elapsedMs / totalDuration);
      const eased = 1 - Math.pow(1 - t, 3);
      let newPct = eased * cap;
      if (elapsedMs > totalDuration) {
        // Overrun creep — never look frozen.
        const overrunS = (elapsedMs - totalDuration) / 1000;
        newPct = Math.min(99, cap + Math.min(4, overrunS / 3));
      }
      setPct(newPct);

      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [active, stages]);

  if (!active) return null;

  const currentStage = stages[stageIdx] ?? stages[stages.length - 1];

  return (
    <div
      className={cn(
        "rounded-xl border border-amber-500/20 bg-amber-500/[0.04] p-4 space-y-3",
        className,
      )}
    >
      {(title || description) && (
        <div>
          {title && (
            <p className="text-sm font-semibold flex items-center gap-2">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-400 op-pulse" />
              {title}
            </p>
          )}
          {description && (
            <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
              {description}
            </p>
          )}
        </div>
      )}

      <ul className="space-y-1.5">
        {stages.map((s, i) => {
          const done = i < stageIdx;
          const isActive = i === stageIdx;
          return (
            <li
              key={i}
              className={cn(
                "flex items-center gap-2.5 text-xs transition-colors",
                done && "text-muted-foreground",
                isActive && "text-foreground font-medium",
                !done && !isActive && "text-muted-foreground/50",
              )}
            >
              <span
                className={cn(
                  "inline-flex h-4 w-4 items-center justify-center rounded-full border text-[9px]",
                  done && "border-emerald-500/40 bg-emerald-500/15 text-emerald-400",
                  isActive && "border-amber-500/40 bg-amber-500/15",
                  !done && !isActive && "border-white/[0.08] bg-white/[0.04]",
                )}
              >
                {done ? "✓" : isActive ? (
                  <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-400 op-pulse-dot" />
                ) : null}
              </span>
              <span>{s.label}</span>
            </li>
          );
        })}
      </ul>

      <div className="space-y-1.5">
        <div className="h-1.5 rounded-full bg-white/[0.05] overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-amber-500 via-amber-400 to-yellow-300 op-fill"
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="flex items-center justify-between text-[10px] text-muted-foreground tabular-nums">
          <span>{Math.round(pct)}%</span>
          <span>{elapsedS.toFixed(1)}s</span>
        </div>
      </div>

      {currentStage?.tip && (
        <p
          className={cn(
            "text-xs text-muted-foreground/80 italic leading-relaxed pt-1 border-t border-white/[0.04]",
            "transition-all duration-200",
            tipVisible ? "opacity-100 blur-0" : "opacity-0 blur-[2px]",
          )}
        >
          {currentStage.tip}
        </p>
      )}

      <style jsx>{`
        .op-pulse {
          animation: op-pulse 1.4s cubic-bezier(0.4, 0, 0.2, 1) infinite;
        }
        .op-pulse-dot {
          animation: op-pulse 1.2s cubic-bezier(0.4, 0, 0.2, 1) infinite;
        }
        .op-fill {
          transition: width 0.6s cubic-bezier(0.23, 1, 0.32, 1);
          box-shadow: 0 0 12px rgba(251, 191, 36, 0.4);
        }
        @keyframes op-pulse {
          0%, 100% {
            transform: scale(1);
            opacity: 0.6;
          }
          50% {
            transform: scale(1.35);
            opacity: 1;
          }
        }
        @media (prefers-reduced-motion: reduce) {
          .op-pulse,
          .op-pulse-dot {
            animation: none;
          }
          .op-fill {
            transition: none;
          }
        }
      `}</style>
    </div>
  );
}
