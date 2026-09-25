"use client";

import { useMemo } from "react";
import Link from "next/link";
import {
  ChevronRight,
  ArrowUpRight,
  Link as LinkIcon,
  Sparkles,
  User as UserIcon,
  Sliders,
} from "lucide-react";

import {
  useAnalytics,
  useAutoApplications,
  useJobs,
  useReviewQueue,
  useReminders,
  useCurrentUser,
} from "@/hooks/use-api";
import { ScoreRing } from "@/components/ds/score";
import { ClosedNote } from "@/components/closed-note";
import { jobFreshness } from "@/lib/freshness";

/* ============================================================
   Dashboard overview — v2 command-center layout.
   No stat cards. Editorial greeting, mono pulse strip, asymmetric
   two-column grid: radar + activity on the left, waiting / sweep
   status / quick actions on the right.
   ============================================================ */

export default function DashboardOverview() {
  // Loading and failure are shown as such. Falling back to 0 made a slow
  // load look like an empty account ("0 discovered, no scored jobs yet").
  const analyticsQuery = useAnalytics();
  const jobsQuery = useJobs({ pageSize: 10, sortBy: "best" });
  const analytics = analyticsQuery.data;
  const jobsData = jobsQuery.data;
  const statsLoading = analyticsQuery.isPending;
  const statsFailed = analyticsQuery.isError && !analytics;
  const { data: reviewQueue } = useReviewQueue();
  const { data: autoApplications } = useAutoApplications();
  const { data: reminders } = useReminders();
  const { data: currentUser } = useCurrentUser();

  // Scored top-of-inbox. The API embeds `score` on each Job for the
  // inbox endpoint; we flatten and sort by overall_fit.
  const scoredJobs = useMemo(() => {
    const list = (jobsData?.jobs ?? []).map((j: any) => ({
      id: j.id as string,
      company: j.company as string,
      // Prefer the English translation when the source was non-English.
      // title_en is NULL on already-English jobs.
      title: (j.title_en || j.title) as string,
      location: (j.location ?? "—") as string,
      salary: j.salary_text as string | null,
      time: jobFreshness(j).short,
      closedNote: (j.closed_note ?? null) as string | null,
      score: j.score?.overall_fit != null ? Math.round(j.score.overall_fit) : null,
    }));
    return list
      .filter((j) => j.score != null)
      .sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
  }, [jobsData]);

  const radar = scoredJobs.slice(0, 5);
  const topMatchCount = scoredJobs.filter((j) => (j.score ?? 0) >= 80).length;

  // Greeting
  const now = useMemo(() => new Date(), []);
  const hr = now.getHours();
  const greeting = hr < 12 ? "Good morning" : hr < 18 ? "Good afternoon" : "Good evening";
  const firstName = formatFirstName(currentUser?.name);
  const dayLine = now.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });

  // Hint logic — show the most-pressing single thing
  // What's waiting on the user in Applications: questions to answer,
  // applications ready to send, and recent resumes to check.
  const withApplication = new Set((autoApplications ?? []).map((a) => a.job_id));
  const monthAgo = now.getTime() - 30 * 86_400_000;
  const reviewReady =
    (autoApplications ?? []).filter((a) => ["needs_you", "queued"].includes(a.status)).length +
    (reviewQueue ?? []).filter(
      (r: any) => r.approval_status === "ready" && !withApplication.has(r.job_id) && new Date(r.updated_at).getTime() > monthAgo,
    ).length;
  const followUps = (reminders ?? []).length;
  const hint = (() => {
    if (reviewReady > 0) {
      return {
        text: `${reviewReady} application${reviewReady === 1 ? "" : "s"} waiting on you`,
        href: "/dashboard/applications",
        tone: "accent" as const,
      };
    }
    if (followUps > 0) {
      return {
        text: `${followUps} follow-up${followUps === 1 ? "" : "s"} due this week`,
        href: "/dashboard/applications",
        tone: "warn" as const,
      };
    }
    if (topMatchCount > 0) {
      return {
        text: `${topMatchCount} hot match${topMatchCount === 1 ? "" : "es"} today · last sweep ${formatSweepTime(analytics?.last_discovery_at)}`,
        href: "/dashboard/jobs",
        tone: "info" as const,
      };
    }
    if (!analytics) return null;
    return {
      text: `Inbox is calm · last sweep ${formatSweepTime(analytics?.last_discovery_at)}`,
      href: "/dashboard/jobs",
      tone: "info" as const,
    };
  })();

  // Stat cards — four-card row, the layout we had before the pulse strip.
  const stats: StatCardData[] = [
    {
      label: "DISCOVERED",
      value: formatNumber(analytics?.jobs_discovered),
      sub:
        analytics?.jobs_shortlisted
          ? `${analytics.jobs_shortlisted} shortlisted`
          : "0 shortlisted",
    },
    {
      label: "WAITING ON YOU",
      value: String(reviewReady),
      sub: "in Applications",
    },
    {
      label: "APPLIED",
      value: formatNumber(analytics?.applications_sent),
      sub:
        analytics?.applications_this_week != null
          ? `${analytics.applications_this_week} this week`
          : "—",
    },
    {
      label: "RESPONSE RATE",
      value:
        (analytics?.applications_sent ?? 0) > 0
          // The API already sends percentages (0–100).
          ? `${Math.round(analytics?.response_rate ?? 0)}%`
          : "—",
      sub: `${Math.round(analytics?.interview_rate ?? 0)}% interview rate`,
    },
  ];

  return (
    <div className="page dash-page">
      {/* Greeting block */}
      <header style={{ marginBottom: 28 }}>
        <div className="ds-mono dash-day">{dayLine.toUpperCase()}</div>
        <h1 className="dash-greeting">
          {greeting}
          {firstName ? <>,{" "}<span>{firstName}.</span></> : "."}
        </h1>

        {hint && (
          <Link href={hint.href} className={`dash-hint dash-hint-${hint.tone}`}>
            <span className="dash-hint-dot" />
            {hint.text}
            <ChevronRight size={14} style={{ opacity: 0.6 }} />
          </Link>
        )}
      </header>

      {/* Stat cards */}
      <StatCards stats={stats} loading={statsLoading} failed={statsFailed} onRetry={() => analyticsQuery.refetch()} />

      {/* Two-column body */}
      <div className="dash-grid">
        {/* LEFT */}
        <div className="dash-left">
          <RadarSection
            radar={radar}
            totalScored={analytics?.jobs_discovered ?? null}
            lastSweep={analytics?.last_discovery_at}
            loading={jobsQuery.isPending}
            failed={jobsQuery.isError && !jobsData}
            onRetry={() => jobsQuery.refetch()}
          />
        </div>

        {/* RIGHT */}
        <aside className="dash-right">
          <WaitingCard reviewReady={reviewReady} followUps={followUps} />
          <QuickActions />
        </aside>
      </div>

      <DashStyle />
    </div>
  );
}

/* ============================================================
   Components
   ============================================================ */

type StatCardData = { label: string; value: string; sub: string };

function StatCards({
  stats,
  loading,
  failed,
  onRetry,
}: {
  stats: StatCardData[];
  loading: boolean;
  failed: boolean;
  onRetry: () => void;
}) {
  return (
    <>
      <div className="dash-stats" aria-busy={loading}>
        {stats.map((s) => (
          <div key={s.label} className="dash-stat">
            <div className="ds-mono dash-stat-label">{s.label}</div>
            {loading ? (
              <>
                <div className="dash-skeleton dash-skeleton-value" />
                <div className="dash-skeleton dash-skeleton-sub" />
              </>
            ) : (
              <>
                <div className="ds-mono dash-stat-value">{failed ? "—" : s.value}</div>
                <div className="dash-stat-sub">{failed ? "Not loaded" : s.sub}</div>
              </>
            )}
          </div>
        ))}
      </div>
      {failed && (
        <p className="dash-load-error">
          Couldn&apos;t load your numbers.{" "}
          <button type="button" onClick={onRetry}>Try again</button>
        </p>
      )}
    </>
  );
}

function RadarSection({
  radar,
  totalScored,
  lastSweep,
  loading,
  failed,
  onRetry,
}: {
  radar: Array<{ id: string; company: string; title: string; location: string; salary: string | null; time: string; closedNote: string | null; score: number | null }>;
  totalScored: number | null;
  lastSweep: string | null | undefined;
  loading: boolean;
  failed: boolean;
  onRetry: () => void;
}) {
  return (
    <section>
      <div className="dash-section-head">
        <div>
          <div className="ds-mono dash-overline">ON YOUR RADAR · TODAY</div>
          <h2 className="dash-h2">The top of the inbox.</h2>
        </div>
        <Link href="/dashboard/jobs" className="dash-ghost-btn">
          Open inbox
          <ChevronRight size={14} />
        </Link>
      </div>
      <div className="dash-card dash-radar-card">
        <div className="dash-radar-head">
          <span className="ds-mono dash-radar-count">
            {loading || totalScored == null ? "BEST MATCHES, NEWEST FIRST" : `${radar.length} OF ${totalScored} · BEST MATCHES, NEWEST FIRST`}
          </span>
          <span className="ds-mono dash-radar-sweep">
            SWEPT {formatSweepTime(lastSweep)}
          </span>
        </div>
        {loading &&
          Array.from({ length: 5 }, (_, i) => (
            <div key={i} className="dash-radar-skeleton">
              <div className="dash-skeleton dash-skeleton-ring" />
              <div style={{ flex: 1 }}>
                <div className="dash-skeleton dash-skeleton-title" />
                <div className="dash-skeleton dash-skeleton-meta" />
              </div>
            </div>
          ))}
        {failed && (
          <div className="dash-radar-empty ds-faint">
            Couldn&apos;t load your matches.{" "}
            <button type="button" className="dash-inline-btn" onClick={onRetry}>Try again</button>
          </div>
        )}
        {!loading && !failed && radar.length === 0 && (
          <div className="dash-radar-empty ds-faint">
            No scored jobs yet. The next sweep will fill this in.
          </div>
        )}
        {radar.map((j) => (
          <RadarRow key={j.id} job={j} />
        ))}
      </div>
    </section>
  );
}

function RadarRow({
  job,
}: {
  job: {
    id: string; company: string; title: string; location: string; salary: string | null;
    time: string; closedNote: string | null; score: number | null;
  };
}) {
  const top = (job.score ?? 0) >= 80;
  return (
    <Link href={`/dashboard/jobs/${job.id}`} className="dash-radar-row">
      <ScoreRing score={job.score} size={44} stroke={2} />
      <div className="dash-radar-body">
        <div className="dash-radar-title-row">
          <span className="dash-radar-title">{job.title}</span>
          {top && <span className="ds-mono dash-radar-tag">◆ top match</span>}
        </div>
        <div className="dash-radar-meta">
          <span className="dash-radar-company">{job.company}</span>
          <span className="dash-sep">·</span>
          <span>{job.location}</span>
          {job.salary && (
            <>
              <span className="dash-sep">·</span>
              <span className="ds-mono dash-radar-salary">{job.salary}</span>
            </>
          )}
          {job.closedNote ? (
            <span className="dash-radar-time"><ClosedNote note={job.closedNote} compact /></span>
          ) : (
            job.time && <span className="ds-mono dash-radar-time">{job.time}</span>
          )}
        </div>
      </div>
      <ArrowUpRight size={15} className="dash-radar-arrow" />
    </Link>
  );
}

function WaitingCard({ reviewReady, followUps }: { reviewReady: number; followUps: number }) {
  const total = reviewReady + followUps;
  return (
    <section className="dash-card">
      <header className="dash-waiting-head">
        <h3 className="dash-h3">Waiting on you</h3>
        <span className="ds-mono dash-waiting-pill">{total}</span>
      </header>
      <div>
        {reviewReady > 0 && (
          <Link href="/dashboard/applications" className="dash-waiting-row">
            <span className="dash-waiting-dot dash-waiting-dot-urgent" />
            <div className="dash-waiting-body">
              <div className="dash-waiting-label">
                {reviewReady === 1 ? "1 application" : `${reviewReady} applications`}
              </div>
              <div className="dash-waiting-target">need your answers or are ready to send</div>
            </div>
            <span className="ds-mono dash-waiting-time">now</span>
          </Link>
        )}
        {followUps > 0 && (
          <Link href="/dashboard/applications" className="dash-waiting-row">
            <span className="dash-waiting-dot dash-waiting-dot-urgent" />
            <div className="dash-waiting-body">
              <div className="dash-waiting-label">
                {followUps === 1 ? "Follow up due" : `${followUps} follow-ups due`}
              </div>
              <div className="dash-waiting-target">applications awaiting your reply</div>
            </div>
            <span className="ds-mono dash-waiting-time">this week</span>
          </Link>
        )}
        {total === 0 && (
          <div className="dash-waiting-empty ds-faint">
            Nothing waiting. Open the inbox to find your next match.
          </div>
        )}
      </div>
    </section>
  );
}

function QuickActions() {
  const actions: Array<{ label: string; href: string; icon: React.ReactNode }> = [
    { label: "Add a job you found", href: "/dashboard/import", icon: <LinkIcon size={15} /> },
    { label: "Your applications", href: "/dashboard/applications", icon: <Sparkles size={15} /> },
    { label: "Update profile", href: "/dashboard/profile", icon: <UserIcon size={15} /> },
    { label: "Adjust matcher weights", href: "/dashboard/profile", icon: <Sliders size={15} /> },
  ];
  return (
    <section className="dash-quick-section">
      <div className="ds-mono dash-overline dash-quick-overline">QUICK ACTIONS</div>
      <div className="dash-quick">
        {actions.map((a) => (
          <Link key={a.label} href={a.href} className="dash-quick-btn">
            <span className="dash-quick-icon">{a.icon}</span>
            <span className="dash-quick-label">{a.label}</span>
            <ChevronRight size={13} className="dash-quick-chev" />
          </Link>
        ))}
      </div>
    </section>
  );
}

/* ============================================================
   Helpers
   ============================================================ */

function formatSweepTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${hh}:${mm} UTC`;
}

function formatNumber(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString("en-US");
}

function formatFirstName(name: string | null | undefined): string {
  const raw = (name ?? "").trim();
  if (!raw) return "";
  if (raw.includes(" ")) {
    const first = raw.split(/\s+/)[0];
    return first[0].toUpperCase() + first.slice(1).toLowerCase();
  }
  // Single token. Treat as a name only if it's short enough to plausibly be a
  // single name ("olalekan"), not an email local-part ("olalekanoderinlo").
  if (raw.length <= 12 && /^[a-z]+$/i.test(raw)) {
    return raw[0].toUpperCase() + raw.slice(1).toLowerCase();
  }
  return "";
}

/* ============================================================
   Scoped CSS — uses v2 tokens via var(--…) and v1 .ds-* utility
   classes already in design-tokens.css. Lives inline so the
   dashboard route stays self-contained; can be extracted once
   sibling dashboard pages move to v2.
   ============================================================ */

function DashStyle() {
  return (
    <style>{`
      .dash-page { padding-top: 32px; max-width: 1280px; margin: 0 auto; padding-left: 28px; padding-right: 28px; padding-bottom: 80px; }
      @media (max-width: 900px) { .dash-page { padding: 18px 16px 96px; } }

      .dash-day {
        font-size: 11px;
        letter-spacing: 0.16em;
        color: var(--fg-faint);
        margin-bottom: 10px;
        font-weight: 600;
      }
      .dash-greeting {
        font-size: clamp(34px, 5vw, 48px);
        letter-spacing: -0.035em;
        line-height: 1.06;
        text-wrap: balance;
        color: var(--fg);
        font-weight: 600;
        margin: 0;
      }
      .dash-greeting span { color: var(--fg-muted); font-weight: 500; }

      .dash-hint {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        margin-top: 16px;
        font-size: 15px;
        transition: color 120ms ease;
        color: var(--fg-muted);
      }
      .dash-hint-accent { color: var(--accent); }
      .dash-hint-warn { color: var(--fg); }
      .dash-hint-info { color: var(--fg-muted); }
      .dash-hint:hover { color: var(--fg); }
      .dash-hint-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: var(--fg-dim);
        flex-shrink: 0;
      }
      .dash-hint-accent .dash-hint-dot { background: var(--accent); box-shadow: 0 0 10px var(--accent); }
      .dash-hint-warn .dash-hint-dot { background: var(--fg-muted); }

      .dash-stats {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 14px;
      }
      @media (max-width: 900px) { .dash-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
      @media (max-width: 540px) { .dash-stats { grid-template-columns: 1fr; } }
      .dash-stat {
        background: var(--bg-elev-1);
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 18px 18px 16px;
        min-width: 0;
      }
      .dash-stat-label {
        font-size: 10px;
        letter-spacing: 0.12em;
        color: var(--fg-faint);
        text-transform: uppercase;
        font-weight: 600;
      }
      .dash-stat-value {
        font-size: 30px;
        font-weight: 600;
        letter-spacing: -0.03em;
        color: var(--fg);
        line-height: 1.1;
        margin-top: 10px;
      }
      .dash-stat-sub {
        font-size: 12px;
        color: var(--fg-muted);
        margin-top: 6px;
      }

      .dash-grid {
        display: grid;
        grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr);
        gap: 32px;
        margin-top: 36px;
      }
      @media (max-width: 900px) { .dash-grid { grid-template-columns: 1fr; gap: 28px; } }
      .dash-left { min-width: 0; display: flex; flex-direction: column; gap: 36px; }
      .dash-right { min-width: 0; display: flex; flex-direction: column; gap: 24px; }

      .dash-section-head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 6px;
        flex-wrap: wrap;
      }
      .dash-overline {
        font-size: 10px;
        letter-spacing: 0.12em;
        color: var(--fg-faint);
        text-transform: uppercase;
        font-weight: 600;
      }
      .dash-h2 {
        font-size: 22px;
        letter-spacing: -0.02em;
        margin: 6px 0 0;
        color: var(--fg);
        font-weight: 600;
        line-height: 1.2;
      }
      .dash-h3 {
        font-size: 14px;
        margin: 0;
        color: var(--fg);
        font-weight: 600;
        letter-spacing: -0.01em;
      }

      .dash-ghost-btn {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 0 10px;
        height: 32px;
        border-radius: 6px;
        color: var(--fg-muted);
        font-size: 13px;
        transition: color 120ms ease, background 120ms ease;
      }
      .dash-ghost-btn:hover { color: var(--fg); background: var(--bg-hover); }

      .dash-card {
        background: var(--bg-elev-1);
        border: 1px solid var(--line);
        border-radius: 8px;
      }
      .dash-radar-card { margin-top: 16px; padding: 0; overflow: hidden; }
      .dash-radar-head {
        padding: 12px 16px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 1px solid var(--line-faint);
      }
      .dash-radar-count {
        font-size: 10px;
        letter-spacing: 0.1em;
        color: var(--fg-dim);
        text-transform: uppercase;
      }
      .dash-radar-sweep {
        font-size: 11px;
        color: var(--fg-faint);
        letter-spacing: 0.1em;
      }
      .dash-radar-empty { padding: 26px 16px; font-size: 13px; }

      /* Loading placeholders: the shape of what's coming, never a false 0. */
      .dash-skeleton { border-radius: 6px; background: var(--ds-bg-elev-2); animation: dash-pulse 1.4s ease-in-out infinite; }
      .dash-skeleton-value { height: 28px; width: 64px; margin: 10px 0 8px; }
      .dash-skeleton-sub { height: 12px; width: 96px; }
      .dash-radar-skeleton { display: flex; align-items: center; gap: 14px; padding: 14px 16px; border-top: 1px solid var(--ds-line); }
      .dash-skeleton-ring { height: 36px; width: 36px; border-radius: 999px; flex: 0 0 36px; }
      .dash-skeleton-title { height: 14px; width: 60%; margin-bottom: 8px; }
      .dash-skeleton-meta { height: 11px; width: 35%; }
      @keyframes dash-pulse { 0%, 100% { opacity: 0.55; } 50% { opacity: 1; } }
      @media (prefers-reduced-motion: reduce) { .dash-skeleton { animation: none; } }
      .dash-load-error { margin: -10px 0 22px; font-size: 13px; color: var(--ds-fg-muted, inherit); }
      .dash-load-error button, .dash-inline-btn { color: var(--ds-accent); text-decoration: underline; background: none; border: 0; padding: 0; cursor: pointer; font: inherit; }

      .dash-radar-row {
        display: grid;
        grid-template-columns: auto 1fr auto;
        gap: 16px;
        align-items: center;
        padding: 16px 16px 16px 18px;
        border-top: 1px solid var(--line-faint);
        min-height: 72px;
        position: relative;
        transition: background 150ms cubic-bezier(0.32,0.72,0.32,1);
      }
      .dash-radar-row:first-child { border-top: 0; }
      .dash-radar-row::before {
        content: "";
        position: absolute;
        left: 0; top: 8px; bottom: 8px;
        width: 1px;
        background: var(--accent);
        transform: scaleY(0);
        transform-origin: top;
        transition: transform 150ms cubic-bezier(0.32,0.72,0.32,1);
      }
      .dash-radar-row:hover { background: var(--bg-hover); }
      .dash-radar-row:hover::before { transform: scaleY(1); }
      .dash-radar-body { min-width: 0; }
      .dash-radar-title-row { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
      .dash-radar-title {
        font-weight: 600;
        font-size: 15.5px;
        letter-spacing: -0.01em;
        color: var(--fg);
      }
      .dash-radar-tag {
        font-size: 10px;
        letter-spacing: 0.12em;
        color: var(--accent);
        text-transform: uppercase;
      }
      .dash-radar-meta {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-top: 4px;
        font-size: 13px;
        color: var(--fg-muted);
        flex-wrap: wrap;
      }
      .dash-radar-company { color: var(--fg); font-weight: 500; }
      .dash-radar-salary { color: var(--fg); }
      .dash-radar-time { color: var(--fg-dim); margin-left: auto; }
      .dash-radar-arrow { color: var(--fg-faint); }

      .dash-sep { color: var(--fg-faint); }

      .dash-activity { margin-top: 16px; padding-top: 4px; }
      .dash-activity-row {
        display: grid;
        grid-template-columns: 60px auto 1fr;
        gap: 14px;
        align-items: baseline;
        padding: 10px 0;
      }
      .dash-activity-when {
        font-size: 11px;
        color: var(--fg-faint);
        letter-spacing: 0.04em;
      }
      .dash-activity-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        align-self: center;
      }
      .dash-activity-dot-accent { background: var(--accent); }
      .dash-activity-dot-muted { background: var(--fg-muted); }
      .dash-activity-dot-dim { background: var(--fg-dim); }
      .dash-activity-text { font-size: 13.5px; line-height: 1.45; }
      .dash-activity-kind { color: var(--fg-muted); }
      .dash-activity-what { color: var(--fg); font-weight: 500; margin-left: 6px; }
      .dash-activity-target { color: var(--fg-muted); }

      .dash-waiting-head {
        padding: 14px 16px 12px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
      }
      .dash-waiting-pill {
        font-size: 11px;
        color: var(--accent);
        background: var(--accent-soft);
        border: 1px solid var(--accent-edge);
        padding: 2px 8px;
        border-radius: 4px;
      }
      .dash-waiting-row {
        display: grid;
        grid-template-columns: auto 1fr auto;
        gap: 12px;
        align-items: center;
        padding: 12px 14px;
        border-top: 1px solid var(--line-faint);
        min-height: 56px;
        position: relative;
        transition: background 150ms cubic-bezier(0.32,0.72,0.32,1);
      }
      .dash-waiting-row:hover { background: var(--bg-hover); }
      .dash-waiting-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: var(--fg-dim);
        flex-shrink: 0;
      }
      .dash-waiting-dot-urgent {
        background: var(--accent);
        box-shadow: 0 0 0 3px rgba(30,216,183,0.15);
      }
      .dash-waiting-body { min-width: 0; }
      .dash-waiting-label {
        font-size: 13.5px;
        font-weight: 600;
        letter-spacing: -0.005em;
        color: var(--fg);
      }
      .dash-waiting-target {
        font-size: 12px;
        color: var(--fg-muted);
        margin-top: 2px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .dash-waiting-time { font-size: 11px; color: var(--fg-dim); }
      .dash-waiting-empty { padding: 16px 16px 22px; font-size: 13px; }

      .dash-sweep { padding: 18px; }
      .dash-sweep-head {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 12px;
      }
      .dash-sweep-dot {
        width: 8px; height: 8px;
        border-radius: 50%;
        background: var(--accent);
        box-shadow: 0 0 8px var(--accent);
      }
      .dash-sweep-rows { display: flex; flex-direction: column; gap: 10px; }
      .dash-sweep-row { display: flex; justify-content: space-between; font-size: 13px; gap: 10px; }
      .dash-sweep-key { color: var(--fg-muted); }
      .dash-sweep-val { color: var(--fg); text-align: right; }
      .dash-sweep-val-dim { color: var(--fg-dim); }
      .dash-sweep-foot {
        margin-top: 14px;
        padding-top: 12px;
        border-top: 1px solid var(--line-faint);
        font-size: 12px;
        color: var(--fg-dim);
        line-height: 1.5;
      }

      .dash-quick-overline { margin-bottom: 8px; padding: 0 2px; }
      /* Hide Quick Actions on mobile — when the dash collapses to a single
         column, the four nav shortcuts become noise next to the sidebar's
         own nav. Desktop keeps them. */
      @media (max-width: 900px) { .dash-quick-section { display: none; } }
      .dash-quick { display: flex; flex-direction: column; gap: 6px; }
      .dash-quick-btn {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px 14px;
        background: var(--bg-elev-1);
        border: 1px solid var(--line);
        border-radius: 8px;
        color: var(--fg-muted);
        font-size: 13.5px;
        transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
      }
      .dash-quick-btn:hover {
        background: var(--bg-elev-2);
        color: var(--fg);
        border-color: var(--line-strong);
      }
      .dash-quick-icon { color: var(--fg-dim); }
      .dash-quick-label { flex: 1; }
      .dash-quick-chev { color: var(--fg-faint); }
    `}</style>
  );
}
