"use client";

import Link from "next/link";
import { Bell, Briefcase, ChevronDown, ChevronRight, FileText, Loader2, Send } from "lucide-react";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  useApplicationPipeline, useAutoApplications, useReminders, useReviewQueue, useUpdateStatus,
} from "@/hooks/use-api";
import { AutoApplyStatusPill } from "@/components/auto-apply-status";
import { ClosedNote } from "@/components/closed-note";
import { useToast } from "@/components/ui/toast";
import { EmptyState } from "@/components/ui/empty-state";
import type { ApplicationTracking, AutoApplication, TailoredApplication } from "@/lib/types";

// A tailored resume nobody opened in a month is history, not a to-do.
const STALE_DAYS = 30;
// Sent applications still waiting to hear back. A job taken down once the
// company is interviewing you is normal, so later stages get no note.
const WAITING_STATUSES = ["approved", "applied", "follow_up_due"];

function daysSince(iso: string | null | undefined) {
  return iso ? (Date.now() - new Date(iso).getTime()) / 86_400_000 : 0;
}

function timeAgo(iso: string | null | undefined) {
  if (!iso) return "";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 60) return minutes < 1 ? "just now" : `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return days < 14 ? `${days}d ago` : `${Math.round(days / 7)}w ago`;
}

/** One row for something still on its way out: an application being
 *  prepared, or a resume written for a job. */
function ToDoRow({ href, company, title, detail, right, note }: {
  href: string; company?: string; title?: string; detail: string; right: React.ReactNode;
  note?: string | null;
}) {
  return (
    <Link href={href} className="ds-row" style={{ gridTemplateColumns: "minmax(0, 1fr) auto auto", alignItems: "center" }}>
      <div className="min-w-0">
        <div className="ds-muted truncate" style={{ fontSize: 13 }}>{company}</div>
        <div className="truncate" style={{ fontSize: 15, fontWeight: 500 }}>{title || "Unknown role"}</div>
        <div className="ds-dim truncate" style={{ fontSize: 12, marginTop: 2 }}>{detail}</div>
        {note && <ClosedNote note={note} />}
      </div>
      <div className="flex items-center" style={{ gap: 10 }}>{right}</div>
      <ChevronRight className="h-4 w-4 ds-dim" />
    </Link>
  );
}

function Section({ title, hint, count, children }: {
  title: string; hint?: string; count: number; children: React.ReactNode;
}) {
  return (
    <section className="space-y-2">
      <div className="flex items-baseline justify-between" style={{ gap: 12 }}>
        <h2 className="ds-h3">
          {title} <span className="ds-mono ds-dim" style={{ fontSize: 13 }}>{count}</span>
        </h2>
        {hint && <span className="ds-dim" style={{ fontSize: 12 }}>{hint}</span>}
      </div>
      <div className="ds-card" style={{ overflow: "hidden" }}>{children}</div>
    </section>
  );
}

function autoDetail(a: AutoApplication) {
  if (a.status === "needs_you") return `${a.open_count} ${a.open_count === 1 ? "question needs" : "questions need"} you`;
  if (a.status === "preparing") return "Reading the form and filling in your answers";
  if (a.status === "queued") return "Answers approved. Fill in the form and send it.";
  return a.error ?? "";
}

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

/** Everything about applying, in one place: what still needs you, what's
 *  ready to send, and what's been sent. It used to be three pages (Review
 *  Queue, Apply for me, Applications) holding parts of the same thing. */
export default function ApplicationsPage() {
  const { data: tracking, isLoading } = useApplicationPipeline();
  const { data: autoApplications, isLoading: autoLoading } = useAutoApplications();
  const { data: tailored } = useReviewQueue();
  const { data: reminders } = useReminders();
  const updateStatus = useUpdateStatus();
  const toast = useToast();

  const items = tracking ?? [];
  const reminderCount = reminders?.length ?? 0;

  const autos = autoApplications ?? [];
  // A sent application is tracked below with everything else that's sent.
  const needsYou = autos.filter((a) => a.status === "needs_you" || a.status === "preparing");
  const readyToSend = autos.filter((a) => a.status === "queued" || a.status === "submitting");
  const stopped = autos.filter((a) => ["failed", "unsupported", "cancelled"].includes(a.status));
  // Resumes written for a job with an application are shown on that
  // application, so only the others are listed on their own.
  const jobsWithApplication = new Set(autos.map((a) => a.job_id));
  const resumes = (tailored ?? []).filter((t: TailoredApplication) => !jobsWithApplication.has(t.job_id));
  const resumesToCheck = resumes.filter(
    (t) => ["ready", "generating", "pending"].includes(t.approval_status) && daysSince(t.updated_at) <= STALE_DAYS,
  );
  const olderResumes = resumes.filter(
    (t) => ["ready", "generating", "pending"].includes(t.approval_status) && daysSince(t.updated_at) > STALE_DAYS,
  );
  const inProgress = needsYou.length + resumesToCheck.length;

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

  if (isLoading || autoLoading) {
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
            <p className="ds-muted" style={{ marginTop: 6, maxWidth: 620 }}>
              Everything you&apos;re applying to: what still needs you, what&apos;s ready to send, and what
              you&apos;ve sent.
            </p>
          </div>
          {reminderCount > 0 && (
            <span className="ds-pill accent">
              <Bell className="h-3 w-3" />
              {reminderCount} follow-up{reminderCount !== 1 ? "s" : ""} due
            </span>
          )}
        </div>

        {inProgress > 0 && (
          <Section title="Needs you" hint="Answer the questions or check the resume" count={inProgress}>
            {needsYou.map((a) => (
              <ToDoRow
                key={a.id}
                href={`/dashboard/auto-apply/${a.id}`}
                company={a.job?.company}
                title={a.job?.title}
                detail={autoDetail(a)}
                right={<AutoApplyStatusPill status={a.status} />}
                note={a.job?.closed_note}
              />
            ))}
            {resumesToCheck.map((t) => (
              <ToDoRow
                key={t.id}
                href="/dashboard/review"
                company={t.job?.company}
                title={t.job?.title}
                detail={t.approval_status === "ready" ? "Resume and cover letter ready to check" : "Writing your resume"}
                note={t.job?.closed_note}
                right={<span className="ds-mono ds-dim hidden sm:inline" style={{ fontSize: 12 }}>
                  <FileText className="inline h-3.5 w-3.5" style={{ verticalAlign: -2 }} /> {timeAgo(t.updated_at)}
                </span>}
              />
            ))}
          </Section>
        )}

        {readyToSend.length > 0 && (
          <Section title="Ready to send" hint="Every answer is approved" count={readyToSend.length}>
            {readyToSend.map((a) => (
              <ToDoRow
                key={a.id}
                href={`/dashboard/auto-apply/${a.id}`}
                company={a.job?.company}
                title={a.job?.title}
                detail={autoDetail(a)}
                right={<AutoApplyStatusPill status={a.status} />}
                note={a.job?.closed_note}
              />
            ))}
          </Section>
        )}

        {(inProgress > 0 || readyToSend.length > 0) && items.length > 0 && (
          <h2 className="ds-overline ds-mono ds-dim" style={{ fontSize: 12, letterSpacing: "0.08em", paddingTop: 8 }}>
            SENT
          </h2>
        )}

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

        {items.length === 0 && inProgress === 0 && readyToSend.length === 0 ? (
          <div className="ds-card">
            <EmptyState
              icon={Briefcase}
              title="Nothing here yet"
              description="Open a job in your inbox and press Apply for me, or mark a job as applied. It shows up here until you hear back."
              action={{ label: "Go to inbox", href: "/dashboard/jobs" }}
            />
          </div>
        ) : items.length === 0 ? null : (
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
                        {item.job?.closed_note && WAITING_STATUSES.includes(status) && (
                          <ClosedNote note={item.job.closed_note} />
                        )}
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

        {(stopped.length > 0 || olderResumes.length > 0) && (
          <details className="space-y-2">
            <summary className="ds-dim" style={{ fontSize: 13, cursor: "pointer" }}>
              Stopped, couldn&apos;t apply, and older resumes ({stopped.length + olderResumes.length})
            </summary>
            <div className="ds-card" style={{ overflow: "hidden", marginTop: 8 }}>
              {stopped.map((a) => (
                <ToDoRow
                  key={a.id}
                  href={`/dashboard/auto-apply/${a.id}`}
                  company={a.job?.company}
                  title={a.job?.title}
                  detail={autoDetail(a)}
                  right={<AutoApplyStatusPill status={a.status} />}
                />
              ))}
              {olderResumes.map((t) => (
                <ToDoRow
                  key={t.id}
                  href="/dashboard/review"
                  company={t.job?.company}
                  title={t.job?.title}
                  detail="Resume written, never sent"
                  right={<span className="ds-mono ds-dim" style={{ fontSize: 12 }}>{timeAgo(t.updated_at)}</span>}
                />
              ))}
            </div>
          </details>
        )}
      </div>
    </div>
  );
}
