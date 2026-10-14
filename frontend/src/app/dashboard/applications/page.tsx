"use client";

import Link from "next/link";
import { Bell, Briefcase, ChevronDown, FileText, Loader2, MessageSquare, Send } from "lucide-react";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  useApplicationPipeline, useAutoApplications, useReminders, useReviewQueue, useUpdateStatus,
} from "@/hooks/use-api";
import { AutoApplyStatusPill } from "@/components/auto-apply-status";
import { ClosedNote } from "@/components/closed-note";
import { FillInFormButton } from "@/components/fill-in-form-button";
import { SendForMe, useSendFinished } from "@/components/send-for-me";
import { AutoPrepareCard } from "@/components/auto-prepare-card";
import { ApplyPicks } from "@/components/apply-picks";
import { ApplyQueue, autoDetail, type SentToday } from "@/components/apply-queue";
import { useToast } from "@/components/ui/toast";
import { EmptyState } from "@/components/ui/empty-state";
import type { ApplicationTracking, AutoApplication, TailoredApplication } from "@/lib/types";

// A tailored resume nobody opened in a month is history, not a to-do.
const STALE_DAYS = 30;
// Sent applications still waiting to hear back. A job taken down once the
// company is interviewing you is normal, so later stages get no note.

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
  ghosted: "No reply",
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
  // No reply for 30 days moves it here by itself; a reply after all moves it back.
  ghosted: ["applied", "interviewing", "rejected"],
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
  useSendFinished(autoApplications);
  const { data: tailored } = useReviewQueue();
  const { data: reminders } = useReminders();
  const updateStatus = useUpdateStatus();
  const toast = useToast();

  const items = tracking ?? [];
  const reminderCount = reminders?.length ?? 0;

  const autos = autoApplications ?? [];
  // In progress: the queue at the top, where each one is checked, approved
  // and sent in place. Sent ones are tracked below with everything else.
  const inQueue = autos.filter((a) => ["preparing", "needs_you", "queued", "submitting"].includes(a.status));
  const stopped = autos.filter((a) => ["failed", "unsupported", "cancelled"].includes(a.status));
  // Sent in the last day, through the app or on their site: next is a note.
  const recent = (iso: string | null | undefined) => !!iso && daysSince(iso) < 1;
  const messageFor = new Map((tracking ?? []).map((t) => [t.job_id, t.message]));
  const sentToday: SentToday[] = [];
  for (const a of autos) {
    if (a.status === "submitted" && recent(a.submitted_at)) {
      sentToday.push({ job_id: a.job_id, company: a.job?.company ?? null, title: a.job?.title ?? null, message: messageFor.get(a.job_id) });
    }
  }
  for (const t of tracking ?? []) {
    if (["applied", "follow_up_due"].includes(t.status) && recent(t.applied_at) && !sentToday.some((s) => s.job_id === t.job_id)) {
      sentToday.push({ job_id: t.job_id, company: t.job?.company ?? null, title: t.job?.title ?? null, message: t.message });
    }
  }
  // Resumes written for a job with an application are shown on that
  // application, so only the others are listed on their own.
  const jobsWithApplication = new Set(autos.map((a) => a.job_id));
  const resumes = (tailored ?? []).filter((t: TailoredApplication) => !jobsWithApplication.has(t.job_id));
  // A resume whose job has closed has nothing left to do, however new.
  const current = (t: TailoredApplication) => daysSince(t.updated_at) <= STALE_DAYS && !t.job?.closed;
  const unsentResumes = resumes.filter((t) => ["ready", "generating", "pending"].includes(t.approval_status));
  const resumesToCheck = unsentResumes.filter(current);
  const olderResumes = unsentResumes.filter((t) => !current(t));
  const inProgress = resumesToCheck.length;

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
    // No following up once it's closed, as in the daily email.
    const due = ["rejected", "ghosted", "archived"].includes(status) ? null : relativeDate(item.follow_up_date);
    const next = NEXT_STATUSES[status] ?? [];
    return (
      <BoardCard
        key={item.id}
        href={`/dashboard/jobs/${item.job_id}`}
        company={item.job?.company}
        title={item.job?.title}
        // Once it's sent, a closed listing changes nothing: the company can
        // still reply, and it moves to No reply after 30 days if not.
        note={status === "approved" ? item.job?.closed_note : null}
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
        {/* Waiting to hear back: a note to someone there, until it's sent or skipped. */}
        {["applied", "follow_up_due"].includes(status) && item.message !== "skipped" && (
          item.message === "sent" ? (
            <span className="ds-dim flex items-center" style={{ fontSize: 12, gap: 4 }}>
              <MessageSquare className="h-3 w-3" />
              Messaged
            </span>
          ) : (
            <Link
              href={`/dashboard/jobs/${item.job_id}#message`}
              className="ds-btn sm"
              title="Who to write to at the company, and a short note to send from your LinkedIn"
            >
              <MessageSquare className="h-3 w-3" />
              Message someone
            </Link>
          )
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
      {(a.status === "queued" || a.sending?.waiting) && (
        <>
          <span style={{ flex: 1 }} />
          {a.sending?.from_browser_only && a.status === "queued" ? (
            <Link href={`/dashboard/auto-apply/${a.id}`} className="ds-btn primary sm">
              Send from your browser
            </Link>
          ) : (
            <>
              <SendForMe application={a} compact />
              {!a.sending?.waiting && <FillInFormButton applicationId={a.id} onlyIfInstalled quiet />}
            </>
          )}
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
  const boardEmpty = items.length === 0 && stopped.length === 0 && resumes.length === 0;

  return (
    <div className="ds-root ds-page-fade" style={{ background: "var(--ds-bg)" }}>
      <div className="space-y-6" style={{ maxWidth: 1480, margin: "0 auto" }}>
        <div className="flex flex-wrap items-end justify-between" style={{ gap: 12 }}>
          <div>
            <h1 className="ds-h1">Applications</h1>
            <p className="ds-muted" style={{ marginTop: 6, maxWidth: 620 }}>
              Apply from here: pick jobs, check what the app filled in, and send, without leaving this page. Below
              is everything you&apos;ve sent and heard back on.
            </p>
          </div>
          {reminderCount > 0 && (
            <span className="ds-pill accent">
              <Bell className="h-3 w-3" />
              {reminderCount} follow-up{reminderCount !== 1 ? "s" : ""} due
            </span>
          )}
        </div>

        <div className="space-y-8" style={{ maxWidth: 1080 }}>
          <ApplyQueue applications={inQueue} sentToday={sentToday} />
          <ApplyPicks />
          <AutoPrepareCard />
        </div>

        {boardEmpty ? (
          nothingYet ? (
            <div className="ds-card">
              <EmptyState
                icon={Briefcase}
                title="Nothing sent yet"
                description="Pick jobs above and prepare them, or mark a job as applied. Everything you send shows up here until you hear back."
              />
            </div>
          ) : null
        ) : (
          <div
            style={{
              display: "grid", gridTemplateColumns: `repeat(auto-fit, minmax(min(${COLUMN_MIN}px, 100%), 1fr))`,
              gap: 12, alignItems: "start",
            }}
          >
            {/* Only stages with something in them. */}
            {inProgress > 0 && (
              <Column title="Resumes to check" hint="Written for jobs you apply to on their site" count={inProgress}>
                {resumesToCheck.map((t) =>
                  resumeCard(t, t.approval_status === "ready" ? "Resume and cover letter ready to check" : "Writing your resume", true),
                )}
              </Column>
            )}
            {approvedToApply.length > 0 && (
              <Column title="Ready to apply" hint="Resume approved. Apply on their site" count={approvedToApply.length}>
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
                {olderResumes.map((t) =>
                  resumeCard(t, t.job?.closed ? "Resume written. The job closed before it was sent." : "Resume written, never sent", false),
                )}
              </Column>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
