"use client";

import Link from "next/link";
import { Bell, Briefcase, ChevronDown, FileText, Loader2, Send } from "lucide-react";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  useApplicationPipeline, useAutoApplications, useReminders, useReviewQueue, useUpdateStatus,
} from "@/hooks/use-api";
import { AutoApplyStatusPill } from "@/components/auto-apply-status";
import { ClosedNote } from "@/components/closed-note";
import { FillInFormButton } from "@/components/fill-in-form-button";
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

/** One application on the board. */
function BoardCard({ href, company, title, detail, note, children }: {
  href: string; company?: string; title?: string; detail?: React.ReactNode;
  note?: string | null; children?: React.ReactNode;
}) {
  return (
    <div className="ds-card" style={{ padding: 12, display: "flex", flexDirection: "column", gap: 6 }}>
      <Link href={href} className="min-w-0" style={{ textDecoration: "none", color: "inherit" }}>
        <div className="ds-muted truncate" style={{ fontSize: 12 }}>{company}</div>
        <div style={{
          fontSize: 14, fontWeight: 500, lineHeight: 1.35,
          display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden",
        }}>
          {title || "Unknown role"}
        </div>
        {detail && <div className="ds-dim" style={{ fontSize: 12, marginTop: 4, lineHeight: 1.45 }}>{detail}</div>}
      </Link>
      {note && <ClosedNote note={note} />}
      {children && <div className="flex flex-wrap items-center" style={{ gap: 6 }}>{children}</div>}
    </div>
  );
}

// The narrowest a column gets. Columns share the width and wrap onto a new
// row when there isn't room, so the board fits any screen: side by side on
// a laptop, one under another on a phone.
const COLUMN_MIN = 250;

/** One stage of applying, as a column. */
function Column({ title, hint, count, children }: {
  title: string; hint?: string; count: number; children: React.ReactNode;
}) {
  return (
    <section
      style={{
        display: "flex", flexDirection: "column", gap: 8, minWidth: 0,
        padding: 10, borderRadius: "var(--ds-r-lg)", border: "1px solid var(--ds-line)",
        background: "var(--ds-bg-chrome)",
      }}
    >
      <header style={{ padding: "2px 4px 4px" }}>
        <div className="flex items-baseline justify-between" style={{ gap: 8 }}>
          <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>{title}</h2>
          <span className="ds-mono ds-dim" style={{ fontSize: 12 }}>{count}</span>
        </div>
        {hint && <div className="ds-dim" style={{ fontSize: 12, marginTop: 2 }}>{hint}</div>}
      </header>
      {children}
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
  past: "#f59e0b", // overdue
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

  const trackedIn = (...statuses: string[]) =>
    STATUS_ORDER.flatMap((status) => items.filter((t) => t.status === status && statuses.includes(status)));
  const approvedToApply = trackedIn("approved");
  const sent = trackedIn("follow_up_due", "applied");
  const talking = trackedIn("interviewing", "offered");
  const closed = trackedIn("rejected", "ghosted", "archived");
  const closedCount = closed.length + stopped.length + olderResumes.length;

  if (isLoading || autoLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const trackedCard = (item: ApplicationTracking, status: string) => {
    const due = relativeDate(item.follow_up_date);
    const next = NEXT_STATUSES[status] ?? [];
    const waiting = WAITING_STATUSES.includes(status);
    return (
      <BoardCard
        key={item.id}
        href={`/dashboard/jobs/${item.job_id}`}
        company={item.job?.company}
        title={item.job?.title}
        note={waiting ? item.job?.closed_note : null}
      >
        <span className="ds-pill" style={{ fontSize: 11 }}>
          <Dot status={status} />
          {STATUS_LABELS[status] ?? status}
        </span>
        {due && (
          <span
            className="ds-mono"
            style={{ fontSize: 12, color: DUE_COLOR[due.tone], fontWeight: due.tone === "due" || due.tone === "past" ? 600 : 400 }}
            title={due.tone === "past" ? "Follow-up overdue" : "Follow-up date"}
          >
            {due.tone === "past" ? `Follow up: ${due.text}` : due.text}
          </span>
        )}
        <span style={{ flex: 1 }} />
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
      </BoardCard>
    );
  };

  const autoCard = (a: AutoApplication) => (
    <BoardCard
      key={a.id}
      href={`/dashboard/auto-apply/${a.id}`}
      company={a.job?.company}
      title={a.job?.title}
      detail={autoDetail(a)}
      note={["failed", "unsupported", "cancelled"].includes(a.status) ? null : a.job?.closed_note}
    >
      <AutoApplyStatusPill status={a.status} />
      {a.status === "queued" && (
        <>
          <span style={{ flex: 1 }} />
          <FillInFormButton applicationId={a.id} />
        </>
      )}
    </BoardCard>
  );

  const resumeCard = (t: TailoredApplication, detail: string, withNote: boolean) => (
    <BoardCard
      key={t.id}
      href="/dashboard/review"
      company={t.job?.company}
      title={t.job?.title}
      detail={detail}
      note={withNote ? t.job?.closed_note : null}
    >
      <span className="ds-dim" style={{ fontSize: 12 }}>
        <FileText className="inline h-3.5 w-3.5" style={{ verticalAlign: -2 }} /> {timeAgo(t.updated_at)}
      </span>
    </BoardCard>
  );

  const nothingYet = items.length === 0 && autos.length === 0 && resumes.length === 0;

  return (
    <div className="ds-root ds-page-fade" style={{ background: "var(--ds-bg)" }}>
      <div className="space-y-6" style={{ maxWidth: 1480, margin: "0 auto" }}>
        <div className="flex flex-wrap items-end justify-between" style={{ gap: 12 }}>
          <div>
            <h1 className="ds-h1">Applications</h1>
            <p className="ds-muted" style={{ marginTop: 6, maxWidth: 620 }}>
              Every application, from the questions that still need you to the ones you&apos;ve heard back on.
            </p>
          </div>
          {reminderCount > 0 && (
            <span className="ds-pill accent">
              <Bell className="h-3 w-3" />
              {reminderCount} follow-up{reminderCount !== 1 ? "s" : ""} due
            </span>
          )}
        </div>

        {nothingYet ? (
          <div className="ds-card">
            <EmptyState
              icon={Briefcase}
              title="Nothing here yet"
              description="Open a job in your inbox and press Apply for me, or mark a job as applied. It shows up here until you hear back."
              action={{ label: "Go to inbox", href: "/dashboard/jobs" }}
            />
          </div>
        ) : (
          <div
            style={{
              display: "grid", gridTemplateColumns: `repeat(auto-fit, minmax(min(${COLUMN_MIN}px, 100%), 1fr))`,
              gap: 12, alignItems: "start",
            }}
          >
            {/* Only stages with something in them. */}
            {inProgress > 0 && (
              <Column title="Needs you" hint="Answer the questions or check the resume" count={inProgress}>
                {needsYou.map(autoCard)}
                {resumesToCheck.map((t) =>
                  resumeCard(t, t.approval_status === "ready" ? "Resume and cover letter ready to check" : "Writing your resume", true),
                )}
              </Column>
            )}
            {readyToSend.length + approvedToApply.length > 0 && (
              <Column title="Ready to send" hint="Everything checked and approved" count={readyToSend.length + approvedToApply.length}>
                {readyToSend.map(autoCard)}
                {approvedToApply.map((item) => trackedCard(item, item.status))}
              </Column>
            )}
            {sent.length > 0 && (
              <Column title="Sent" hint="Waiting to hear back" count={sent.length}>
                {sent.map((item) => trackedCard(item, item.status))}
              </Column>
            )}
            {talking.length > 0 && (
              <Column title="Interviews and offers" count={talking.length}>
                {talking.map((item) => trackedCard(item, item.status))}
              </Column>
            )}
            {closedCount > 0 && (
              <Column title="Closed" hint="Heard no, stopped, or put away" count={closedCount}>
                {closed.map((item) => trackedCard(item, item.status))}
                {stopped.map(autoCard)}
                {olderResumes.map((t) => resumeCard(t, "Resume written, never sent", false))}
              </Column>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
