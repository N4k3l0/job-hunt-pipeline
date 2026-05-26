"use client";

import { useMemo, Fragment } from "react";
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
  useJobs,
  useReviewQueue,
  useReminders,
  useCurrentUser,
} from "@/hooks/use-api";
import { ScoreRing } from "@/components/ds/score";

/* ============================================================
   Dashboard overview — v2 command-center layout.
   No stat cards. Editorial greeting, mono pulse strip, asymmetric
   two-column grid: radar + activity on the left, waiting / sweep
   status / quick actions on the right.
   ============================================================ */

export default function DashboardOverview() {
  const { data: analytics } = useAnalytics();
  const { data: jobsData } = useJobs({ pageSize: 10, sortBy: "score" });
  const { data: reviewQueue } = useReviewQueue();
  const { data: reminders } = useReminders();
  const { data: currentUser } = useCurrentUser();

  // Scored top-of-inbox. The API embeds `score` on each Job for the
  // inbox endpoint; we flatten and sort by overall_fit.
  const scoredJobs = useMemo(() => {
    const list = (jobsData?.jobs ?? []).map((j: any) => ({
      id: j.id as string,
      company: j.company as string,
      title: j.title as string,
      location: (j.location ?? "—") as string,
      salary: j.salary_text as string | null,
      time: j.discovered_at ? timeAgo(j.discovered_at) : "",
      score: j.score?.overall_fit != null ? Math.round(j.score.overall_fit) : null,
    }));
    return list
      .filter((j) => j.score != null)
      .sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
  }, [jobsData]);

  const radar = scoredJobs.slice(0, 3);
  const topMatchCount = scoredJobs.filter((j) => (j.score ?? 0) >= 80).length;

  // Greeting
  const now = useMemo(() => new Date(), []);
  const hr = now.getHours();
  const greeting = hr < 12 ? "Good morning" : hr < 18 ? "Good afternoon" : "Good evening";
  const firstName = formatFirstName(currentUser?.name);
  const dayLine = now.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });

  // Hint logic — show the most-pressing single thing
  const reviewReady = (reviewQueue ?? []).filter((r: any) => r.approval_status === "ready").length;
  const followUps = (reminders ?? []).length;
  const hint = (() => {
    if (reviewReady > 0) {
      return {
        text: `${reviewReady} tailored application${reviewReady === 1 ? "" : "s"} ready to review`,
        href: "/dashboard/review",
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
    return {
      text: `Inbox is calm · last sweep ${formatSweepTime(analytics?.last_discovery_at)}`,
      href: "/dashboard/jobs",
      tone: "info" as const,
    };
  })();

  // Pulse strip
  const pulse: PulseItem[] = [
    { value: formatNumber(analytics?.jobs_discovered), label: "scored" },
    { value: String(topMatchCount), label: "top matches", accent: true },
    { value: formatNumber(analytics?.jobs_shortlisted), label: "shortlisted" },
    { value: formatNumber(analytics?.applications_sent), label: "applied" },
    {
      value: String(Math.round((analytics?.response_rate ?? 0) * (analytics?.applications_sent ?? 0))),
      label: "replies",
    },
    {
      value: `${Math.round((analytics?.response_rate ?? 0) * 100)}%`,
      label: "response",
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

        <Link href={hint.href} className={`dash-hint dash-hint-${hint.tone}`}>
          <span className="dash-hint-dot" />
          {hint.text}
          <ChevronRight size={14} style={{ opacity: 0.6 }} />
        </Link>
      </header>

      {/* Pulse strip */}
      <PulseStrip items={pulse} />

      {/* Two-column body */}
      <div className="dash-grid">
        {/* LEFT */}
        <div className="dash-left">
          <RadarSection
            radar={radar}
            totalScored={analytics?.jobs_discovered ?? 0}
            lastSweep={analytics?.last_discovery_at}
          />
          <ActivityFeed
            lastSweep={analytics?.last_discovery_at}
            topMatchCount={topMatchCount}
            reviewReady={reviewReady}
            applicationsSent={analytics?.applications_sent ?? 0}
          />
        </div>

        {/* RIGHT */}
        <aside className="dash-right">
          <WaitingCard reviewReady={reviewReady} followUps={followUps} />
          <SweepStatusCard lastSweep={analytics?.last_discovery_at} />
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

type PulseItem = { value: string; label: string; accent?: boolean };

function PulseStrip({ items }: { items: PulseItem[] }) {
  return (
    <div className="dash-pulse">
      {items.map((it, i) => (
        <Fragment key={it.label}>
          {i > 0 && <span className="dash-pulse-sep">·</span>}
          <div className="dash-pulse-item">
            <span className={`ds-mono dash-pulse-n${it.accent ? " dash-pulse-accent" : ""}`}>
              {it.value}
            </span>
            <span className="ds-mono dash-pulse-l">{it.label}</span>
          </div>
        </Fragment>
      ))}
    </div>
  );
}

function RadarSection({
  radar,
  totalScored,
  lastSweep,
}: {
  radar: Array<{ id: string; company: string; title: string; location: string; salary: string | null; time: string; score: number | null }>;
  totalScored: number;
  lastSweep: string | null | undefined;
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
            {radar.length} OF {totalScored} · SCORE &gt; 80
          </span>
          <span className="ds-mono dash-radar-sweep">
            SWEPT {formatSweepTime(lastSweep)}
          </span>
        </div>
        {radar.length === 0 && (
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
  job: { id: string; company: string; title: string; location: string; salary: string | null; time: string; score: number | null };
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
          {job.time && <span className="ds-mono dash-radar-time">{job.time}</span>}
        </div>
      </div>
      <ArrowUpRight size={15} className="dash-radar-arrow" />
    </Link>
  );
}

function ActivityFeed({
  lastSweep,
  topMatchCount,
  reviewReady,
  applicationsSent,
}: {
  lastSweep: string | null | undefined;
  topMatchCount: number;
  reviewReady: number;
  applicationsSent: number;
}) {
  // Built from analytics + last-sweep timestamp. A richer feed would need a
  // dedicated activity endpoint; this is enough to be useful today.
  const items: Array<{ when: string; kind: string; what: string; target?: string; tone?: "accent" | "muted" }> = [];
  if (lastSweep) {
    items.push({
      when: formatSweepTime(lastSweep),
      kind: "Daily sweep",
      what: `${topMatchCount} new at 80+`,
      tone: "accent",
    });
  }
  if (reviewReady > 0) {
    items.push({
      when: "today",
      kind: "Tailored",
      what: `${reviewReady} application${reviewReady === 1 ? "" : "s"} ready to review`,
      tone: "accent",
    });
  }
  if (applicationsSent > 0) {
    items.push({
      when: "this week",
      kind: "Sent",
      what: `${applicationsSent} application${applicationsSent === 1 ? "" : "s"} total`,
      tone: "muted",
    });
  }
  if (items.length === 0) {
    items.push({ when: "—", kind: "Activity", what: "Nothing yet. Check back after the next sweep." });
  }

  return (
    <section>
      <div className="ds-mono dash-overline">RECENT ACTIVITY · 24H</div>
      <h2 className="dash-h2">What&apos;s happened since yesterday.</h2>
      <div className="dash-activity">
        {items.map((it, i) => (
          <div key={i} className="dash-activity-row">
            <span className="ds-mono dash-activity-when">{it.when}</span>
            <span className={`dash-activity-dot dash-activity-dot-${it.tone ?? "dim"}`} />
            <div className="dash-activity-text">
              <span className="dash-activity-kind">{it.kind}</span>
              <span className="dash-activity-what">{it.what}</span>
              {it.target && (
                <>
                  <span className="dash-sep">·</span>
                  <span className="dash-activity-target">{it.target}</span>
                </>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
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
          <Link href="/dashboard/review" className="dash-waiting-row">
            <span className="dash-waiting-dot dash-waiting-dot-urgent" />
            <div className="dash-waiting-body">
              <div className="dash-waiting-label">
                {reviewReady === 1 ? "Review tailored application" : `${reviewReady} tailored applications`}
              </div>
              <div className="dash-waiting-target">in your review queue</div>
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

function SweepStatusCard({ lastSweep }: { lastSweep: string | null | undefined }) {
  return (
    <section className="dash-card dash-sweep">
      <div className="dash-sweep-head">
        <span className="dash-sweep-dot" />
        <h3 className="dash-h3">Sweep status</h3>
      </div>
      <div className="dash-sweep-rows">
        <div className="dash-sweep-row">
          <span className="dash-sweep-key">Last sweep</span>
          <span className="ds-mono dash-sweep-val">
            {lastSweep ? formatSweepFull(lastSweep) : "—"}
          </span>
        </div>
        <div className="dash-sweep-row">
          <span className="dash-sweep-key">Next sweep</span>
          <span className="ds-mono dash-sweep-val dash-sweep-val-dim">06:00 UTC · daily</span>
        </div>
        <div className="dash-sweep-row">
          <span className="dash-sweep-key">Sources tracked</span>
          <span className="ds-mono dash-sweep-val">curated boards + careers pages</span>
        </div>
      </div>
      <div className="dash-sweep-foot">All systems nominal. Matcher v2 calibrated.</div>
    </section>
  );
}

function QuickActions() {
  const actions: Array<{ label: string; href: string; icon: React.ReactNode }> = [
    { label: "Import a job URL", href: "/dashboard/import", icon: <LinkIcon size={15} /> },
    { label: "Tailor an application", href: "/dashboard/review", icon: <Sparkles size={15} /> },
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

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

function formatSweepTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${hh}:${mm} UTC`;
}

function formatSweepFull(iso: string): string {
  const d = new Date(iso);
  const sweep = formatSweepTime(iso);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  if (sameDay) return `${sweep} · today`;
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) return `${sweep} · yesterday`;
  return `${sweep} · ${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`;
}

function formatNumber(n: number | null | undefined): string {
  if (n == null) return "0";
  return String(n);
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

      .dash-pulse {
        display: flex;
        align-items: baseline;
        gap: 14px;
        flex-wrap: wrap;
        padding: 18px 0;
        border-top: 1px solid var(--line);
        border-bottom: 1px solid var(--line);
      }
      .dash-pulse-sep {
        color: var(--fg-faint);
        font-family: var(--font-mono);
      }
      .dash-pulse-item { display: flex; align-items: baseline; gap: 6px; }
      .dash-pulse-n {
        font-size: 22px;
        font-weight: 600;
        letter-spacing: -0.03em;
        color: var(--fg);
      }
      .dash-pulse-accent { color: var(--accent); }
      .dash-pulse-l {
        font-size: 10px;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: var(--fg-dim);
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
