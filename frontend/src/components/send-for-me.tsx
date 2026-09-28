"use client";

import { useEffect, useRef, useState } from "react";
import { CheckCircle2, Eye, Loader2, Send } from "lucide-react";
import { useSendForMe } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api-client";
import type { AutoApplication, AutoApplySendOutcome } from "@/lib/types";

/** "Send it for me": the app's own browser fills in the company's form and
 *  sends it, so nothing needs installing or pasting. A practice run fills it
 *  in without sending and keeps a picture of the form. */
export function SendForMe({ application, compact = false }: { application: AutoApplication; compact?: boolean }) {
  const send = useSendForMe(application.id);
  const toast = useToast();
  const waiting = application.sending?.waiting;
  const company = application.job?.company ?? "the company";

  if (application.status !== "queued" && !waiting) return null;

  if (waiting) {
    return (
      <span className="ds-dim inline-flex items-center" style={{ fontSize: 12, gap: 6 }}>
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        {waiting.running
          ? waiting.practice ? "Filling in the form for practice now" : "Sending it now"
          : waiting.practice ? "Practice run within about 5 minutes" : "Sending within about 5 minutes"}
      </span>
    );
  }

  function ask(practice: boolean) {
    if (!practice && !window.confirm(`Send your application to ${company} now? This can't be undone.`)) return;
    send.mutate(practice, {
      onSuccess: () =>
        toast.success(practice ? "Practice run on its way" : "On its way", {
          description: practice
            ? "Within about 5 minutes the app fills in the form, without sending it, and shows you what it filled in."
            : "Within about 5 minutes the app fills in the form and sends it. You can close this page.",
        }),
      onError: (e) => toast.error("Couldn't start it", { description: e.message }),
    });
  }

  return (
    <span className="inline-flex flex-wrap items-center" style={{ gap: 6 }}>
      <button
        type="button"
        className="ds-btn primary sm"
        disabled={send.isPending}
        onClick={(e) => {
          e.preventDefault();
          ask(false);
        }}
      >
        {send.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
        Send it for me
      </button>
      <button
        type="button"
        className="ds-btn ghost sm"
        disabled={send.isPending}
        onClick={(e) => {
          e.preventDefault();
          ask(true);
        }}
        title="Fill in the form without sending it, and see what the app filled in"
      >
        {compact ? "Practice" : "Practice run first"}
      </button>
    </span>
  );
}

/** Says how it went when a send or practice run finishes while the page is
 *  open. Otherwise the spinner just stops and the card looks the same. */
export function useSendFinished(applications: AutoApplication[] | undefined) {
  const toast = useToast();
  const waiting = useRef<Map<string, boolean> | null>(null);

  useEffect(() => {
    if (!applications) return;
    const before = waiting.current;
    const now = new Map<string, boolean>();
    for (const a of applications) {
      if (a.sending?.waiting) {
        now.set(a.id, a.sending.waiting.practice);
        continue;
      }
      if (!before?.has(a.id)) continue;
      const practice = before.get(a.id);
      const outcome = practice ? a.sending?.practice : a.sending?.send;
      const company = a.job?.company ?? "The company";
      if (!outcome) continue;
      if (outcome.status === "submitted") {
        toast.success(`Sent to ${company}`, { description: outcome.message });
      } else if (outcome.status === "dry_run") {
        toast.success("Practice run done", { description: outcome.message });
      } else {
        toast.error(practice ? "The practice run stopped" : `Not sent to ${company}`, { description: outcome.message });
      }
    }
    waiting.current = now;
  }, [applications, toast]);
}

/** How the last practice run or send went, with the picture of the form. */
export function SendOutcome({ applicationId, what, outcome }: {
  applicationId: string;
  what: "practice" | "send";
  outcome: AutoApplySendOutcome | null | undefined;
}) {
  const toast = useToast();
  const [opening, setOpening] = useState(false);
  if (!outcome) return null;
  const good = outcome.status === "dry_run" || outcome.status === "submitted";

  async function openPicture() {
    setOpening(true);
    try {
      const { url } = await api.get<{ url: string }>(`/api/v1/auto-apply/${applicationId}/send-screenshot?what=${what}`);
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (e) {
      toast.error("Couldn't open the picture", { description: e instanceof Error ? e.message : undefined });
    } finally {
      setOpening(false);
    }
  }

  return (
    <div style={{ fontSize: 13, lineHeight: 1.5 }}>
      <div className={good ? "" : "text-amber-500"}>
        {good && <CheckCircle2 className="inline h-4 w-4 ds-accent-fg" style={{ marginRight: 6, verticalAlign: -3 }} />}
        {outcome.message}
        {outcome.filled != null && good && ` It filled in ${outcome.filled} ${outcome.filled === 1 ? "answer" : "answers"}.`}
      </div>
      {outcome.not_filled.length > 0 && (
        <div className="text-amber-500" style={{ fontSize: 12, marginTop: 4 }}>
          Couldn&apos;t fill in: {outcome.not_filled.join(", ")}.
        </div>
      )}
      {outcome.has_screenshot && (
        <button type="button" className="ds-btn ghost sm" style={{ marginTop: 6 }} onClick={openPicture} disabled={opening}>
          {opening ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Eye className="h-3.5 w-3.5" />}
          See the form as the app filled it in
        </button>
      )}
    </div>
  );
}
