"use client";

import { useState } from "react";
import Link from "next/link";
import { CheckCircle2, ExternalLink, Loader2, Send } from "lucide-react";
import { useApplyPicks, usePickedElsewhere, usePrepareBatch } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";
import type { ApplyPick } from "@/lib/types";

const SHOWN = 10;

function money(usd: number) {
  return usd < 1 ? `${Math.round(usd * 100)} cents` : `$${usd.toFixed(2)}`;
}

function PickRow({ pick, children }: { pick: ApplyPick; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center" style={{ gap: 10, padding: "9px 12px", borderTop: "1px solid var(--ds-line-faint)" }}>
      <span
        className="ds-mono"
        title="How well it matches your profile"
        style={{ width: 30, textAlign: "right", fontSize: 13, fontWeight: 600, color: "var(--ds-accent)" }}
      >
        {pick.score}
      </span>
      <div className="min-w-0" style={{ flex: "1 1 240px" }}>
        <Link
          href={`/dashboard/jobs/${pick.job_id}`}
          target="_blank"
          className="truncate"
          style={{ display: "block", fontSize: 14, fontWeight: 500, color: "inherit" }}
          title="Open the job in a new tab"
        >
          {pick.title}
        </Link>
        <div className="ds-muted truncate" style={{ fontSize: 12 }}>
          {pick.company}
          {pick.location ? ` · ${pick.location}` : ""}
          {pick.applied_recently && (
            <span className="text-amber-500"> · You started one with {pick.company} this month</span>
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-center" style={{ gap: 6 }}>{children}</div>
    </div>
  );
}

/** The jobs to apply to, best first, on the same page as the queue: tick
 *  the ones the app fills in and prepare them together, or open the ones
 *  on other sites and mark them applied. */
export function ApplyPicks() {
  const toast = useToast();
  const { data, isLoading } = useApplyPicks();
  const prepare = usePrepareBatch();
  const elsewhere = usePickedElsewhere();
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [allFill, setAllFill] = useState(false);
  const [allElsewhere, setAllElsewhere] = useState(false);

  if (isLoading) {
    return <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />;
  }
  if (!data) return null;

  const max = data.max_batch;
  const fill = data.fill;
  const shownFill = allFill ? fill : fill.slice(0, SHOWN);
  const shownElsewhere = allElsewhere ? data.elsewhere : data.elsewhere.slice(0, SHOWN);
  const ids = fill.map((p) => p.job_id).filter((id) => chosen.has(id));

  const flip = (id: string) => {
    if (!chosen.has(id) && chosen.size >= max) {
      toast.error(`Up to ${max} at a time`, { description: "Prepare these first, then pick more." });
      return;
    }
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setChosen(next);
  };
  const takeTop = (n: number) => {
    setChosen(new Set(fill.slice(0, Math.min(n, max)).map((p) => p.job_id)));
    if (n > SHOWN) setAllFill(true);
  };
  const start = () =>
    prepare.mutate(ids, {
      onSuccess: ({ queued }) => {
        setChosen(new Set());
        toast.success(`Preparing ${queued} ${queued === 1 ? "application" : "applications"}`, {
          description: "They show up in your queue as each one is ready, about a minute each.",
        });
      },
      onError: (e) => toast.error("Couldn't start preparing", { description: e.message }),
    });
  const act = (pick: ApplyPick, action: "mark-applied" | "dismiss") =>
    elsewhere.mutate(
      { jobId: pick.job_id, action },
      {
        onSuccess: () =>
          toast.success(action === "mark-applied" ? "Marked as applied" : "Taken off your list", {
            description: action === "mark-applied" ? `${pick.company}: it's under Sent today in your queue.` : undefined,
          }),
        onError: (e) => toast.error("Couldn't save that", { description: e.message }),
      },
    );

  return (
    <section className="space-y-4">
      <div>
        <h2 className="ds-h3">Jobs to apply to</h2>
        <p className="ds-muted" style={{ fontSize: 13, marginTop: 4 }}>
          Your best new matches, scoring 70 or more, that you haven&apos;t started. Nothing is sent until you check it.
        </p>
      </div>

      {fill.length + data.elsewhere.length === 0 && (
        <div className="ds-card ds-muted" style={{ padding: 16, fontSize: 14 }}>
          No new matches to apply to right now. New jobs come in every morning.
        </div>
      )}

      {fill.length > 0 && (
        <div className="ds-card" style={{ padding: 0, overflow: "hidden" }}>
          <div className="flex flex-wrap items-center justify-between" style={{ gap: 10, padding: "12px 12px 10px" }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600 }}>The app fills these in ({fill.length})</div>
              <div className="ds-dim" style={{ fontSize: 12 }}>
                Tick the ones you want. The app writes a resume for each and answers the form, about{" "}
                {money(data.cost_each_usd)} of AI each.
              </div>
            </div>
            <div className="flex flex-wrap items-center" style={{ gap: 6 }}>
              <button type="button" className="ds-btn ghost sm" onClick={() => takeTop(10)}>Top 10</button>
              <button type="button" className="ds-btn ghost sm" onClick={() => takeTop(20)}>Top 20</button>
              {chosen.size > 0 && (
                <button type="button" className="ds-btn ghost sm" onClick={() => setChosen(new Set())}>Clear</button>
              )}
              <button
                type="button"
                className="ds-btn primary sm"
                onClick={start}
                disabled={!ids.length || prepare.isPending}
              >
                {prepare.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
                {ids.length
                  ? `Prepare ${ids.length} (about ${money(ids.length * data.cost_each_usd)})`
                  : "Prepare"}
              </button>
            </div>
          </div>
          {shownFill.map((pick) => (
            <PickRow key={pick.job_id} pick={pick}>
              <button
                type="button"
                className="ds-btn ghost sm"
                onClick={() => {
                  if (chosen.has(pick.job_id)) flip(pick.job_id);
                  act(pick, "dismiss");
                }}
                disabled={elsewhere.isPending}
                title="Take it off the list and out of your inbox"
              >
                Not for me
              </button>
              <input
                type="checkbox"
                checked={chosen.has(pick.job_id)}
                onChange={() => flip(pick.job_id)}
                aria-label={`Prepare ${pick.title} at ${pick.company}`}
                style={{ width: 18, height: 18, accentColor: "var(--ds-accent)", cursor: "pointer" }}
              />
            </PickRow>
          ))}
          {fill.length > SHOWN && (
            <button
              type="button"
              className="ds-btn ghost sm"
              style={{ margin: "6px 8px 10px" }}
              onClick={() => setAllFill(!allFill)}
            >
              {allFill ? "Show fewer" : `Show all ${fill.length}`}
            </button>
          )}
        </div>
      )}

      {data.elsewhere.length > 0 && (
        <div className="ds-card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ padding: "12px 12px 10px" }}>
            <div style={{ fontSize: 14, fontWeight: 600 }}>On other sites ({data.elsewhere.length})</div>
            <div className="ds-dim" style={{ fontSize: 12 }}>
              The app can&apos;t fill these in. Open the job, apply there, then press I applied.
            </div>
          </div>
          {shownElsewhere.map((pick) => (
            <PickRow key={pick.job_id} pick={pick}>
              {pick.url && (
                <a href={pick.url} target="_blank" rel="noopener noreferrer" className="ds-btn sm">
                  <ExternalLink className="h-3.5 w-3.5" /> Open their site
                </a>
              )}
              <button type="button" className="ds-btn ghost sm" onClick={() => act(pick, "mark-applied")} disabled={elsewhere.isPending}>
                <CheckCircle2 className="h-3.5 w-3.5" /> I applied
              </button>
              <button type="button" className="ds-btn ghost sm" onClick={() => act(pick, "dismiss")} disabled={elsewhere.isPending}>
                Not for me
              </button>
            </PickRow>
          ))}
          {data.elsewhere.length > SHOWN && (
            <button
              type="button"
              className="ds-btn ghost sm"
              style={{ margin: "6px 8px 10px" }}
              onClick={() => setAllElsewhere(!allElsewhere)}
            >
              {allElsewhere ? "Show fewer" : `Show all ${data.elsewhere.length}`}
            </button>
          )}
        </div>
      )}
    </section>
  );
}
