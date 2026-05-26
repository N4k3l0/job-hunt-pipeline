"use client";

import { useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * Collapsible profile section card — implements the v2 Profile spec:
 * clickable header toggles expand/collapse, chevron rotates 180° on open,
 * persists state to localStorage keyed by `storageKey` so a user's
 * collapsed sections survive a page reload.
 *
 * Drop-in replacement for `<Card>` blocks on the Profile page. The header
 * slot replaces CardTitle/CardDescription, body slot replaces CardContent.
 */
export function ProfileSection({
  storageKey,
  title,
  icon,
  subtitle,
  defaultOpen = false,
  children,
}: {
  storageKey: string;
  title: React.ReactNode;
  icon?: React.ReactNode;
  subtitle?: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(`profile-section:${storageKey}`);
      if (stored === "open") setOpen(true);
      else if (stored === "closed") setOpen(false);
    } catch {
      // localStorage blocked — fall back to defaultOpen.
    }
    setHydrated(true);
  }, [storageKey]);

  function toggle() {
    const next = !open;
    setOpen(next);
    try {
      localStorage.setItem(`profile-section:${storageKey}`, next ? "open" : "closed");
    } catch {
      // ignore
    }
  }

  return (
    <Card className="overflow-hidden">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="w-full text-left transition-colors hover:bg-[var(--bg-hover,transparent)]"
      >
        <CardHeader className="flex flex-row items-center justify-between gap-3 py-4">
          <div className="flex items-center gap-3 min-w-0">
            {icon && <span className="text-[var(--fg-muted)] flex-shrink-0">{icon}</span>}
            <div className="min-w-0">
              <div className="text-[15px] font-semibold tracking-tight truncate">{title}</div>
              {subtitle && (
                <div className="text-xs text-[var(--fg-muted)] mt-0.5 truncate">{subtitle}</div>
              )}
            </div>
          </div>
          <ChevronDown
            size={16}
            strokeWidth={2}
            className={cn(
              "flex-shrink-0 text-[var(--fg-muted)] transition-transform duration-200",
              open && "rotate-180",
            )}
          />
        </CardHeader>
      </button>
      {/* Only mount body when open AND hydrated so SSR + localStorage agree.
          Setting hidden=true post-hydration would flash content. */}
      {hydrated && open && (
        <CardContent className="pt-0">{children}</CardContent>
      )}
    </Card>
  );
}
