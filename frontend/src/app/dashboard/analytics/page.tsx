"use client";

import { Loader2 } from "lucide-react";
import { useAnalytics } from "@/hooks/use-api";

function StatTile({ label, value, sub, isPercent }: { label: string; value: number; sub: string; isPercent?: boolean }) {
  // Zeros read as a dash so a fresh account doesn't look like failure.
  const display = value === 0 ? "—" : isPercent ? `${value.toFixed(0)}%` : value.toLocaleString();
  return (
    <div className="ds-card" style={{ padding: "18px 18px 16px", minWidth: 0 }}>
      <div
        className="ds-mono"
        style={{ fontSize: 10, letterSpacing: "0.12em", color: "var(--ds-fg-faint)", textTransform: "uppercase", fontWeight: 600 }}
      >
        {label}
      </div>
      <div
        className="ds-mono"
        style={{
          fontSize: 30, fontWeight: 600, letterSpacing: "-0.03em", lineHeight: 1.1, marginTop: 10,
          color: value === 0 ? "var(--ds-fg-faint)" : "var(--ds-fg)",
        }}
      >
        {display}
      </div>
      <div className="ds-muted" style={{ fontSize: 12, marginTop: 6 }}>{sub}</div>
    </div>
  );
}

export default function AnalyticsPage() {
  const { data: analytics, isLoading } = useAnalytics();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const discovered = analytics?.jobs_discovered ?? 0;
  const shortlisted = analytics?.jobs_shortlisted ?? 0;
  const applied = analytics?.applications_sent ?? 0;
  const thisWeek = analytics?.applications_this_week ?? 0;
  const responseRate = analytics?.response_rate ?? 0;
  const interviewRate = analytics?.interview_rate ?? 0;

  // Funnel = Discovered → Shortlisted → Applied → Responses → Interviews.
  // Response and interview counts derive from rate × applied.
  const responses = Math.round(applied * (responseRate / 100));
  const interviews = Math.round(applied * (interviewRate / 100));
  const hasAnyData = discovered > 0 || applied > 0;

  const funnel = [
    { label: "Discovered", count: discovered },
    { label: "Shortlisted", count: shortlisted },
    { label: "Applied", count: applied },
    { label: "Responses", count: responses },
    { label: "Interviews", count: interviews },
  ];
  const peak = Math.max(...funnel.map((f) => f.count), 1);

  const stats = [
    { label: "Discovered", value: discovered, sub: `${shortlisted} shortlisted` },
    { label: "Applied", value: applied, sub: `${thisWeek} this week` },
    { label: "Responses", value: responses, sub: applied > 0 ? `from ${applied} applied` : "no data yet" },
    { label: "Interviews", value: interviews, sub: applied > 0 ? `from ${applied} applied` : "no data yet" },
    { label: "Response rate", value: responseRate, sub: "of all applications", isPercent: true },
    { label: "Interview rate", value: interviewRate, sub: "of all applications", isPercent: true },
  ];

  return (
    <div className="ds-root ds-page-fade" style={{ background: "var(--ds-bg)" }}>
      <div className="space-y-6" style={{ maxWidth: 1100, margin: "0 auto" }}>
        <div>
          <h1 className="ds-h1">Analytics</h1>
          <p className="ds-muted" style={{ marginTop: 6 }}>Where your pipeline stands and how it&apos;s converting.</p>
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-3" style={{ gap: 14 }}>
          {stats.map((s) => (
            <StatTile key={s.label} {...s} />
          ))}
        </div>

        <section className="ds-card" style={{ padding: 18 }}>
          <h2 className="ds-h3">Pipeline funnel</h2>
          <p className="ds-dim" style={{ fontSize: 13, marginTop: 4 }}>
            {hasAnyData
              ? "From discovery through to interview, in absolute counts."
              : "Once jobs start flowing in and you apply, the funnel fills in here."}
          </p>
          <div className="space-y-3" style={{ marginTop: 16 }}>
            {funnel.map((stage, i) => {
              const pct = hasAnyData && stage.count > 0 ? Math.max((stage.count / peak) * 100, 1.5) : 0;
              return (
                <div key={stage.label} className="grid items-center" style={{ gridTemplateColumns: "96px minmax(0, 1fr) 64px", gap: 12 }}>
                  <span className="ds-muted" style={{ fontSize: 13 }}>{stage.label}</span>
                  <div style={{ height: 10, borderRadius: 999, background: "var(--ds-bg-elev-2)", overflow: "hidden" }}>
                    <div
                      style={{
                        height: "100%",
                        width: `${pct}%`,
                        borderRadius: 999,
                        background: "var(--ds-accent)",
                        // One accent, fading down the funnel.
                        opacity: 1 - i * 0.15,
                        transition: "width 500ms var(--ds-ease)",
                      }}
                    />
                  </div>
                  <span
                    className="ds-mono"
                    style={{ fontSize: 13, textAlign: "right", color: stage.count === 0 ? "var(--ds-fg-faint)" : "var(--ds-fg)" }}
                  >
                    {stage.count === 0 ? "—" : stage.count.toLocaleString()}
                  </span>
                </div>
              );
            })}
          </div>
          {!hasAnyData && (
            <p className="ds-dim" style={{ fontSize: 13, marginTop: 14 }}>
              Discovery is running. Check back after your first few applications.
            </p>
          )}
        </section>
      </div>
    </div>
  );
}
