"use client";

import Link from "next/link";
import { Bell, Briefcase, ChevronDown, Loader2, Send } from "lucide-react";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useApplicationPipeline, useUpdateStatus, useReminders } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";
import { EmptyState } from "@/components/ui/empty-state";
import type { ApplicationTracking } from "@/lib/types";

/** Format a date string ("YYYY-MM-DD") relative to today: "Today",
 *  "Tomorrow", "in 3 days", "3 days ago". Empty input returns null.
 */
function relativeDate(input: string | null | undefined): { text: string; tone: "due" | "soon" | "past" | "neutral" } | null {
  if (!input) return null;
  const target = new Date(input + "T00:00:00");
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const ms = target.getTime() - today.getTime();
  const days = Math.round(ms / (1000 * 60 * 60 * 24));
  if (days === 0) return { text: "Today", tone: "due" };
  if (days === 1) return { text: "Tomorrow", tone: "soon" };
  if (days === -1) return { text: "Yesterday", tone: "past" };
  if (days > 0 && days <= 7) return { text: `in ${days} days`, tone: "soon" };
  if (days < 0) return { text: `${Math.abs(days)} days ago`, tone: "past" };
  return { text: target.toLocaleDateString(undefined, { month: "short", day: "numeric" }), tone: "neutral" };
}

const STATUS_LABELS: Record<string, string> = {
  approved: "Approved",
  applied: "Applied",
  follow_up_due: "Follow-up due",
  interviewing: "Interviewing",
  offered: "Offered",
  rejected: "Rejected",
  ghosted: "Ghosted",
  archived: "Archived",
};

const STATUS_ORDER = ["follow_up_due", "interviewing", "approved", "applied", "offered", "rejected", "ghosted", "archived"];

// One accent, no traffic lights: teal marks what's live or needs you,
// grey marks what's waiting, faint marks what's closed.
const STATUS_DOT: Record<string, string> = {
  follow_up_due: "var(--ds-accent)",
  interviewing: "var(--ds-accent)",
  offered: "var(--ds-accent)",
  approved: "var(--ds-fg-muted)",
  applied: "var(--ds-fg-muted)",
  rejected: "var(--ds-fg-faint)",
  ghosted: "var(--ds-fg-faint)",
  archived: "var(--ds-fg-faint)",
};

const DUE_COLOR = {
  due: "var(--ds-accent)",
  past: "var(--ds-accent)",
  soon: "var(--ds-fg-muted)",
  neutral: "var(--ds-fg-dim)",
};

// Next steps offered in each row's menu.
const NEXT_STATUSES: Record<string, string[]> = {
  approved: ["applied"],
  applied: ["interviewing", "rejected"],
  follow_up_due: ["interviewing", "ghosted"],
  interviewing: ["offered", "rejected"],
};

function Dot({ status }: { status: string }) {
  return (
    <span
      aria-hidden
      style={{ width: 8, height: 8, borderRadius: "50%", background: STATUS_DOT[status] ?? "var(--ds-fg-faint)", flexShrink: 0 }}
    />
  );
}

export default function ApplicationsPage() {
  const { data: tracking, isLoading } = useApplicationPipeline();
  const { data: reminders } = useReminders();
  const updateStatus = useUpdateStatus();
  const toast = useToast();

  const items = tracking ?? [];
  const reminderCount = reminders?.length ?? 0;

  const changeStatus = (item: ApplicationTracking, status: string) => {
    updateStatus.mutate(
      { id: item.id, status },
      {
        onSuccess: () =>
          toast.success(`Marked as ${STATUS_LABELS[status] ?? status}`, {
            description: item.job?.title ? `${item.job.company} — ${item.job.title}` : undefined,
          }),
        onError: (err) => toast.error("Status update failed", { description: err.message }),
      },
    );
  };

  const grouped = STATUS_ORDER
    .map((status) => ({ status, items: items.filter((t) => t.status === status) }))
    .filter((group) => group.items.length > 0);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="ds-root ds-page-fade" style={{ background: "var(--ds-bg)" }}>
      <div className="space-y-6" style={{ maxWidth: 900, margin: "0 auto" }}>
        <div className="flex flex-wrap items-end justify-between" style={{ gap: 12 }}>
          <div>
            <h1 className="ds-h1">Applications</h1>
            <p className="ds-muted" style={{ marginTop: 6 }}>
              <span className="ds-mono">{items.length}</span> tracked
            </p>
          </div>
          {reminderCount > 0 && (
            <span className="ds-pill accent">
              <Bell className="h-3 w-3" />
              {reminderCount} follow-up{reminderCount !== 1 ? "s" : ""} due
            </span>
          )}
        </div>

        {grouped.length > 1 && (
          <div className="flex flex-wrap" style={{ gap: 8 }}>
            {grouped.map(({ status, items: statusItems }) => (
              <span key={status} className="ds-pill">
                <Dot status={status} />
                {STATUS_LABELS[status]}
                <span className="ds-mono" style={{ color: "var(--ds-fg)" }}>{statusItems.length}</span>
              </span>
            ))}
          </div>
        )}

        {items.length === 0 ? (
          <div className="ds-card">
            <EmptyState
              icon={Briefcase}
              title="No applications tracked yet"
              description="Jobs you mark as applied, from the Review Queue or a job's page, show up here grouped by status."
              action={{ label: "Open Review Queue", href: "/dashboard/review" }}
            />
          </div>
        ) : (
          grouped.map(({ status, items: statusItems }) => (
            <section key={status} className="space-y-2">
              <div className="flex items-center" style={{ gap: 8 }}>
                <Dot status={status} />
                <h2 className="ds-h3">{STATUS_LABELS[status]}</h2>
                <span className="ds-mono ds-dim" style={{ fontSize: 13 }}>{statusItems.length}</span>
              </div>
              <div className="ds-card" style={{ overflow: "hidden" }}>
                {statusItems.map((item) => {
                  const due = relativeDate(item.follow_up_date);
                  const next = NEXT_STATUSES[status] ?? [];
                  return (
                    <div
                      key={item.id}
                      className="ds-row"
                      style={{ gridTemplateColumns: "minmax(0, 1fr) auto", alignItems: "center" }}
                    >
                      <Link href={`/dashboard/jobs/${item.job_id}`} className="min-w-0">
                        <div className="truncate" style={{ fontSize: 15, fontWeight: 500 }}>
                          {item.job?.title || "Unknown role"}
                        </div>
                        <div className="ds-muted truncate" style={{ fontSize: 13, marginTop: 2 }}>
                          {item.job?.company || ""}
                        </div>
                      </Link>
                      <div className="flex items-center" style={{ gap: 8 }}>
                        {due && (
                          <span
                            className="ds-mono"
                            style={{ fontSize: 12, color: DUE_COLOR[due.tone], fontWeight: due.tone === "due" ? 600 : 400 }}
                            title="Follow-up date"
                          >
                            {due.text}
                          </span>
                        )}
                        {status === "approved" && (
                          <button
                            type="button"
                            className="ds-btn primary sm"
                            onClick={() => changeStatus(item, "applied")}
                            title="Mark this application as applied"
                          >
                            <Send className="h-3 w-3" />
                            Mark applied
                          </button>
                        )}
                        {status !== "archived" && (
                          <DropdownMenu>
                            <DropdownMenuTrigger
                              render={
                                <button type="button" className="ds-btn ghost sm" aria-label="Change status">
                                  <ChevronDown className="h-3.5 w-3.5" />
                                </button>
                              }
                            />
                            <DropdownMenuContent align="end">
                              {next.map((nextStatus) => (
                                <DropdownMenuItem key={nextStatus} onClick={() => changeStatus(item, nextStatus)}>
                                  Mark as {STATUS_LABELS[nextStatus].toLowerCase()}
                                </DropdownMenuItem>
                              ))}
                              <DropdownMenuItem onClick={() => changeStatus(item, "archived")}>Archive</DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          ))
        )}
      </div>
    </div>
  );
}
