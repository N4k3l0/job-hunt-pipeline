"use client";

import { type ComponentType, type ReactNode } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

type EmptyStateProps = {
  /** lucide-react icon — rendered inside a soft glowing chip. */
  icon?: ComponentType<{ className?: string }>;
  /** Big-and-friendly main message. Sentence case. */
  title: string;
  /** One sentence on what's missing and (optionally) what unlocks the state. */
  description?: ReactNode;
  /** Optional primary action — either an href (renders as Link) or onClick. */
  action?: { label: string; href?: string; onClick?: () => void };
  className?: string;
};

/**
 * One source of truth for every empty card in the app.
 * Per Impeccable's "distill repeated patterns" principle — six ad-hoc
 * "No X yet" messages collapse into one consistently-polished surface.
 *
 * Visual:
 *   - Subtle glowing icon chip (warm amber wash)
 *   - Tight type hierarchy (display title, muted body)
 *   - Single primary action when relevant
 *   - Stagger entry: icon → title → desc → action, ~70 ms apart
 *   - Respects prefers-reduced-motion
 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center text-center px-6 py-12 sm:py-16",
        "[--ease-out:cubic-bezier(0.23,1,0.32,1)]",
        className,
      )}
    >
      {Icon && (
        <div
          className={cn(
            "relative mb-5 inline-flex h-14 w-14 items-center justify-center",
            "rounded-2xl border border-amber-500/15 bg-amber-500/[0.04]",
            "shadow-[0_0_32px_-8px_rgba(251,191,36,0.25)]",
            "animate-empty-pop",
          )}
          aria-hidden
        >
          <div className="absolute inset-0 rounded-2xl bg-gradient-to-b from-amber-500/[0.06] to-transparent" />
          <Icon className="relative h-6 w-6 text-amber-400/90" />
        </div>
      )}
      <h3 className="font-display text-lg font-semibold tracking-tight animate-empty-fadeup [animation-delay:70ms]">
        {title}
      </h3>
      {description && (
        <p className="mt-2 max-w-sm text-sm text-muted-foreground leading-relaxed animate-empty-fadeup [animation-delay:140ms]">
          {description}
        </p>
      )}
      {action && (
        <div className="mt-5 animate-empty-fadeup [animation-delay:210ms]">
          {action.href ? (
            <Button size="sm" render={<Link href={action.href} />}>
              {action.label}
            </Button>
          ) : (
            <Button size="sm" onClick={action.onClick}>
              {action.label}
            </Button>
          )}
        </div>
      )}

      {/* Animation styles. Inlined so any consumer page works without
          having to register keyframes globally. Stagger via animation-delay
          on each row gives the cascading enter Emil recommends. */}
      <style jsx>{`
        @keyframes empty-pop {
          from {
            opacity: 0;
            transform: scale(0.92);
          }
          to {
            opacity: 1;
            transform: scale(1);
          }
        }
        @keyframes empty-fadeup {
          from {
            opacity: 0;
            transform: translateY(6px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }
        .animate-empty-pop {
          animation: empty-pop 420ms var(--ease-out) both;
        }
        .animate-empty-fadeup {
          animation: empty-fadeup 360ms var(--ease-out) both;
        }
        @media (prefers-reduced-motion: reduce) {
          .animate-empty-pop,
          .animate-empty-fadeup {
            animation: none;
            opacity: 1;
            transform: none;
          }
        }
      `}</style>
    </div>
  );
}
