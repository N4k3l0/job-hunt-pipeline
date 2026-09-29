"use client";

import { Loader2, Sparkles } from "lucide-react";
import { useAutoPrepareSettings, useUpdateAutoPrepareSettings } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";

/** How many of the user's best new matches the app prepares by itself each
 *  day. They land in Needs you; nothing is sent without the user. */
export function AutoPrepareCard() {
  const { data } = useAutoPrepareSettings();
  const update = useUpdateAutoPrepareSettings();
  const toast = useToast();
  if (!data) return null;

  function choose(perDay: number) {
    update.mutate(perDay, {
      onSuccess: () =>
        toast.success(perDay ? `Up to ${perDay} a day` : "Turned off", {
          description: perDay
            ? "They show up under Needs you as the app prepares them, within the next hour or so."
            : "The app won't prepare any by itself. Apply for me still works.",
        }),
      onError: (e) => toast.error("Couldn't change it", { description: e.message }),
    });
  }

  return (
    <div className="ds-card flex flex-wrap items-center justify-between" style={{ padding: 16, gap: 12 }}>
      <div style={{ maxWidth: 640 }}>
        <div className="flex items-center" style={{ gap: 8, fontWeight: 600, fontSize: 14 }}>
          <Sparkles className="h-4 w-4 ds-accent-fg" />
          Let the app prepare your best matches
        </div>
        <p className="ds-muted" style={{ fontSize: 13, marginTop: 4, lineHeight: 1.5 }}>
          Each day it picks new jobs scoring {data.min_score} or more on forms it can fill in, one per company. It
          writes the resume and the answers and puts them under Needs you. Nothing is sent without you. Each one
          uses about ${data.cost_each_usd.toFixed(2)} of AI.
        </p>
      </div>
      <div className="flex flex-wrap items-center" style={{ gap: 6 }} role="radiogroup" aria-label="Applications a day">
        {data.choices.map((n) => (
          <button
            key={n}
            type="button"
            role="radio"
            aria-checked={data.per_day === n}
            className={`ds-btn sm ${data.per_day === n ? "primary" : "ghost"}`}
            disabled={update.isPending}
            onClick={() => data.per_day !== n && choose(n)}
          >
            {n === 0 ? "Off" : n}
          </button>
        ))}
        <span className="ds-dim" style={{ fontSize: 12 }}>a day</span>
        {update.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
      </div>
    </div>
  );
}
