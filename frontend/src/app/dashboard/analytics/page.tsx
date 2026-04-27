"use client";

import {
  Card, CardContent, CardHeader, CardTitle, CardDescription,
} from "@/components/ui/card";
import {
  Loader2, TrendingUp, Briefcase, FileText, BarChart3, CheckCircle2, Clock, Phone,
} from "lucide-react";
import { useAnalytics } from "@/hooks/use-api";

function StatTile({
  label, value, sub, icon: Icon, isPercent,
}: {
  label: string; value: number; sub: string;
  icon: React.ElementType; isPercent?: boolean;
}) {
  // Keep zeros muted so a fresh account doesn't read as failure.
  const isZero = value === 0;
  const display = isPercent ? `${value.toFixed(0)}%` : value;
  return (
    <div className="rounded-xl border border-white/[0.06] bg-white/[0.015] p-4 transition-colors hover:border-white/[0.12]">
      <div className="flex items-center gap-2 mb-2.5">
        <Icon className="h-3.5 w-3.5 text-muted-foreground/70" />
        <span className="text-[11px] uppercase tracking-[0.1em] text-muted-foreground font-medium">
          {label}
        </span>
      </div>
      <span className={`text-3xl font-bold tracking-tight tabular-nums block ${isZero ? "text-muted-foreground/30" : ""}`}>
        {isZero ? "—" : display}
      </span>
      <span className="text-xs text-muted-foreground/70 mt-1 block">{sub}</span>
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

  const a = analytics;
  const discovered = a?.jobs_discovered ?? 0;
  const shortlisted = a?.jobs_shortlisted ?? 0;
  const applied = a?.applications_sent ?? 0;
  const thisWeek = a?.applications_this_week ?? 0;
  const responseRate = a?.response_rate ?? 0;
  const interviewRate = a?.interview_rate ?? 0;

  // Funnel = Discovered → Shortlisted → Applied → Responses → Interviews.
  // Compute counts (response/interview counts derive from rate × applied).
  const responses = Math.round(applied * (responseRate / 100));
  const interviews = Math.round(applied * (interviewRate / 100));
  const hasAnyData = discovered > 0 || applied > 0;

  const funnel = [
    { label: "Discovered", count: discovered, color: "bg-blue-400/70" },
    { label: "Shortlisted", count: shortlisted, color: "bg-violet-400/70" },
    { label: "Applied", count: applied, color: "bg-amber-400/70" },
    { label: "Responses", count: responses, color: "bg-emerald-400/70" },
    { label: "Interviews", count: interviews, color: "bg-emerald-500/80" },
  ];
  const peak = Math.max(...funnel.map((f) => f.count), 1);

  const stats: { label: string; value: number; sub: string; icon: React.ElementType; isPercent?: boolean }[] = [
    { label: "Discovered", value: discovered, sub: `${shortlisted} shortlisted`, icon: Briefcase },
    { label: "Applied", value: applied, sub: `${thisWeek} this week`, icon: FileText },
    { label: "Responses", value: responses, sub: applied > 0 ? `from ${applied} applied` : "no data yet", icon: CheckCircle2 },
    { label: "Interviews", value: interviews, sub: applied > 0 ? `from ${applied} applied` : "no data yet", icon: Phone },
    { label: "Response Rate", value: responseRate, sub: "of all applications", icon: TrendingUp, isPercent: true },
    { label: "Interview Rate", value: interviewRate, sub: "of all applications", icon: BarChart3, isPercent: true },
  ];

  return (
    <div className="space-y-6 sm:space-y-8">
      <div>
        <h1 className="font-display text-2xl sm:text-3xl font-semibold tracking-tight">Analytics</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Where your pipeline stands and how it&apos;s converting.
        </p>
      </div>

      {/* Stat tiles */}
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-3">
        {stats.map((s) => (
          <StatTile key={s.label} {...s} />
        ))}
      </div>

      {/* Funnel — replaces the empty 'Activity Over Time' placeholder with
          something that's actually useful even at low volume. */}
      <Card className="border-white/[0.06]">
        <CardHeader>
          <CardTitle className="text-sm">Pipeline funnel</CardTitle>
          <CardDescription>
            {hasAnyData
              ? "From discovery through to interview, in absolute counts."
              : "Once jobs start flowing in and you apply, the funnel will populate here."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {funnel.map((stage) => {
            const pct = hasAnyData ? (stage.count / peak) * 100 : 0;
            return (
              <div key={stage.label} className="flex items-center gap-3">
                <span className="w-24 shrink-0 text-xs text-muted-foreground">
                  {stage.label}
                </span>
                <div className="flex-1 h-7 rounded-md bg-white/[0.03] overflow-hidden relative">
                  <div
                    className={`h-full ${stage.color} transition-all duration-500`}
                    style={{ width: `${Math.max(pct, hasAnyData && stage.count === 0 ? 0 : 1.5)}%` }}
                  />
                  <span className="absolute inset-0 flex items-center px-3 text-xs font-medium tabular-nums">
                    {stage.count === 0 ? (
                      <span className="text-muted-foreground/40">—</span>
                    ) : (
                      stage.count
                    )}
                  </span>
                </div>
              </div>
            );
          })}
          {!hasAnyData && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground/70 pt-2">
              <Clock className="h-3.5 w-3.5" />
              Discovery is running — check back after your first few applications.
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
