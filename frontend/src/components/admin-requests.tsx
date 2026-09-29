"use client";

import { useState } from "react";
import { CheckCircle2, Inbox, Loader2, Mail, MessageSquare, RotateCcw } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { useFeedbackList, useInviteRequests, useSetFeedbackResolved } from "@/hooks/use-api";

function ago(iso: string | null | undefined) {
  if (!iso) return "";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days < 1) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** People who asked for an invite on the homepage. Each one can be invited
 *  in one press; people who already have an account are marked. */
export function InviteRequestsCard({
  existingEmails,
  onInvite,
  inviting,
}: {
  existingEmails: Set<string>;
  onInvite: (email: string) => void;
  inviting: string | null;
}) {
  const { data: requests, isLoading, isError } = useInviteRequests();
  const rows = requests ?? [];
  const waiting = rows.filter((r) => !existingEmails.has(r.email.toLowerCase())).length;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Inbox className="h-5 w-5" />
          Invite requests
          {waiting > 0 && <span className="ds-pill accent" style={{ fontSize: 12 }}>{waiting} waiting</span>}
        </CardTitle>
        <CardDescription>People who asked for an invite on the homepage. Newest first.</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        ) : isError ? (
          <p className="text-sm text-muted-foreground">Couldn&apos;t load the requests. Reload the page to try again.</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">No requests yet.</p>
        ) : (
          <div className="divide-y divide-[var(--ds-line)]">
            {rows.map((r) => {
              const hasAccount = existingEmails.has(r.email.toLowerCase());
              return (
                <div key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">{r.email}</div>
                    <div className="text-xs text-muted-foreground">
                      Asked {ago(r.created_at)}
                      {r.source ? ` · from the ${r.source === "hero" ? "top of the homepage" : "invite section"}` : ""}
                    </div>
                  </div>
                  {hasAccount ? (
                    <span className="text-xs text-muted-foreground">Has an account</span>
                  ) : (
                    <Button size="sm" onClick={() => onInvite(r.email)} disabled={inviting !== null}>
                      {inviting === r.email ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Mail className="h-3.5 w-3.5" />}
                      Send invite
                    </Button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

const CATEGORY_LABELS: Record<string, string> = { bug: "Problem", feature: "Idea", general: "Note" };

/** What users sent with the feedback button. Open items first; mark each
 *  one resolved once it's dealt with. */
export function FeedbackCard() {
  const toast = useToast();
  const [show, setShow] = useState<"open" | "resolved">("open");
  const { data: items, isLoading, isError } = useFeedbackList(show === "resolved");
  const setResolved = useSetFeedbackResolved();
  const { data: openItems } = useFeedbackList(false);
  const openCount = openItems?.length ?? 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <MessageSquare className="h-5 w-5" />
          Feedback
          {openCount > 0 && <span className="ds-pill accent" style={{ fontSize: 12 }}>{openCount} open</span>}
        </CardTitle>
        <CardDescription>Problems, ideas and notes from the feedback button, newest first.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex gap-2">
          {(["open", "resolved"] as const).map((v) => (
            <button key={v} type="button" className="ds-chip" data-active={show === v} onClick={() => setShow(v)}>
              {v === "open" ? "Open" : "Resolved"}
            </button>
          ))}
        </div>
        {isLoading ? (
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        ) : isError ? (
          <p className="text-sm text-muted-foreground">Couldn&apos;t load feedback. Reload the page to try again.</p>
        ) : (items ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground">{show === "open" ? "Nothing open." : "Nothing resolved yet."}</p>
        ) : (
          <div className="divide-y divide-[var(--ds-line)]">
            {(items ?? []).map((f) => (
              <div key={f.id} className="space-y-1.5 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span className="ds-pill" style={{ fontSize: 11 }}>{CATEGORY_LABELS[f.category] ?? f.category}</span>
                    <span>{f.user_name || f.user_email || "Someone"} · {ago(f.created_at)}</span>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={setResolved.isPending}
                    onClick={() =>
                      setResolved.mutate(
                        { id: f.id, resolved: !f.resolved },
                        { onError: (e) => toast.error("Couldn't update it", { description: e.message }) },
                      )
                    }
                  >
                    {f.resolved ? <RotateCcw className="h-3.5 w-3.5" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                    {f.resolved ? "Reopen" : "Mark resolved"}
                  </Button>
                </div>
                <p className="whitespace-pre-wrap text-sm">{f.message}</p>
                {f.context && <p className="text-xs text-muted-foreground">On: {f.context}</p>}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
