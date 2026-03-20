"use client";

import { useMemo } from "react";
import Link from "next/link";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardAction,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Briefcase,
  ClipboardCheck,
  FileText,
  TrendingUp,
  ArrowUpRight,
  MapPin,
  Clock,
  Link as LinkIcon,
  Plus,
  Radar,
  ChevronRight,
  Globe,
  Zap,
  Sparkles,
  CircleDot,
} from "lucide-react";
import { useAnalytics, useJobs, useReviewQueue, useReminders } from "@/hooks/use-api";

// Data is now fetched from the API via hooks in the component

function timeAgo(dateStr: string) {
  const diff = Date.now() - new Date(dateStr).getTime();
  const hours = Math.floor(diff / (1000 * 60 * 60));
  if (hours < 1) return "now";
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

function ScoreRing({ score, size = 44 }: { score: number; size?: number }) {
  const strokeWidth = 3;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;
  const color = score >= 85 ? "#34d399" : score >= 70 ? "#fbbf24" : "#6b7280";

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2} cy={size / 2} r={radius}
          fill="none" stroke="currentColor" strokeWidth={strokeWidth}
          className="text-white/[0.04]"
        />
        <circle
          cx={size / 2} cy={size / 2} r={radius}
          fill="none" stroke={color} strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className="transition-all duration-1000 ease-out"
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center font-mono text-xs font-bold tabular-nums">
        {score}
      </span>
    </div>
  );
}

function StatCard({
  label, value, sub, icon: Icon, gradient, delay,
}: {
  label: string; value: string | number; sub: string;
  icon: React.ElementType; gradient: string; delay: number;
}) {
  return (
    <div
      className="relative overflow-hidden rounded-xl border border-white/[0.06] p-5 transition-all duration-300 hover:border-white/[0.12] hover:shadow-lg hover:shadow-black/20"
      style={{
        background: "linear-gradient(135deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0.01) 100%)",
        animationDelay: `${delay}ms`,
      }}
    >
      <div className={`absolute -top-8 -right-8 h-28 w-28 rounded-full blur-2xl opacity-20 ${gradient}`} />
      <div className="relative">
        <div className="flex items-center gap-2 mb-3">
          <Icon className="h-4 w-4 text-muted-foreground" />
          <span className="text-xs uppercase tracking-[0.12em] text-muted-foreground font-semibold">
            {label}
          </span>
        </div>
        <span className="font-mono text-4xl font-bold tracking-tight block">
          {value}
        </span>
        <span className="text-sm text-muted-foreground mt-1.5 block">{sub}</span>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const { data: analytics } = useAnalytics();
  const { data: jobsData } = useJobs({ pageSize: 5, sortBy: "score" });
  const { data: reviewQueue } = useReviewQueue();
  const { data: reminders } = useReminders();

  const stats = {
    jobs_discovered: analytics?.jobs_discovered ?? 0,
    jobs_shortlisted: analytics?.jobs_shortlisted ?? 0,
    applications_sent: analytics?.applications_sent ?? 0,
    response_rate: analytics?.response_rate ?? 0,
    interview_rate: analytics?.interview_rate ?? 0,
    applications_this_week: analytics?.applications_this_week ?? 0,
    review_queue: analytics?.review_queue ?? 0,
  };

  const topJobs = (jobsData?.jobs ?? []).map((j: any) => ({
    ...j,
    score: j.score?.overall_fit ?? 0,
    role_path: j.score?.role_path ?? "pm",
    salary_text: j.salary_text ?? "",
    discovered_at: j.discovered_at,
  }));

  const actions = [
    ...(reviewQueue ?? []).map((r: any) => ({
      id: r.id,
      type: "review" as const,
      label: "Review tailored application",
      target: r.job_id,
      urgency: "high" as const,
      time: new Date(r.created_at).toLocaleDateString(),
    })),
    ...(reminders ?? []).map((r: any) => ({
      id: r.id,
      type: "follow_up" as const,
      label: "Follow up due",
      target: r.job?.title ? `${r.job.company} — ${r.job.title}` : r.job_id,
      urgency: "medium" as const,
      time: r.follow_up_date ?? "",
    })),
  ];

  const now = useMemo(() => new Date(), []);
  const greeting =
    now.getHours() < 12 ? "Good morning"
      : now.getHours() < 18 ? "Good afternoon"
        : "Good evening";

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-end justify-between">
        <div>
          <p className="text-[11px] uppercase tracking-[0.25em] text-muted-foreground font-medium mb-1.5">
            {now.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}
          </p>
          <h1 className="text-3xl font-bold tracking-tight">{greeting}</h1>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" render={<Link href="/dashboard/import" />}>
            <Plus className="h-3.5 w-3.5" />
            Import
          </Button>
          <Button size="sm" render={<Link href="/dashboard/jobs" />}>
            <Radar className="h-3.5 w-3.5" />
            View inbox
          </Button>
        </div>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          icon={Briefcase} label="Discovered" value={stats.jobs_discovered}
          sub={`${stats.jobs_shortlisted} shortlisted`}
          gradient="bg-blue-500" delay={0}
        />
        <StatCard
          icon={ClipboardCheck} label="Review Queue"
          value={actions.filter(a => a.type === "review").length}
          sub="awaiting review"
          gradient="bg-amber-500" delay={80}
        />
        <StatCard
          icon={FileText} label="Applied" value={stats.applications_sent}
          sub={`${stats.applications_this_week} this week`}
          gradient="bg-emerald-500" delay={160}
        />
        <StatCard
          icon={TrendingUp} label="Response Rate"
          value={`${stats.response_rate.toFixed(0)}%`}
          sub={`${stats.interview_rate.toFixed(0)}% interview rate`}
          gradient="bg-violet-500" delay={240}
        />
      </div>

      {/* Main Grid */}
      <div className="grid gap-5 lg:grid-cols-5">
        {/* Top Jobs — 3 cols */}
        <div className="lg:col-span-3 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <Sparkles className="h-4 w-4 text-amber-400" />
              <h2 className="text-sm font-semibold">Top matches</h2>
              <Badge variant="secondary" className="font-mono text-[10px]">24h</Badge>
            </div>
            <Button variant="ghost" size="sm" render={<Link href="/dashboard/jobs" />}>
              All jobs <ChevronRight className="h-3.5 w-3.5" />
            </Button>
          </div>

          <div className="rounded-xl border border-white/[0.06] overflow-hidden" style={{ background: "linear-gradient(180deg, rgba(255,255,255,0.02) 0%, transparent 100%)" }}>
            {topJobs.map((job, i) => (
              <Link
                key={job.id}
                href={`/dashboard/jobs/${job.id}`}
                className={`group flex items-center gap-4 px-4 py-3.5 transition-all hover:bg-white/[0.03] ${
                  i > 0 ? "border-t border-white/[0.04]" : ""
                }`}
              >
                <ScoreRing score={job.score} />

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium truncate">{job.title}</span>
                    <span className={`shrink-0 font-mono text-[9px] px-1.5 py-0.5 rounded-md border ${
                      job.role_path === "pm"
                        ? "border-blue-500/20 text-blue-400 bg-blue-500/5"
                        : "border-emerald-500/20 text-emerald-400 bg-emerald-500/5"
                    }`}>
                      {job.role_path === "pm" ? "PM" : "AI"}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground">
                    <span className="font-medium text-foreground/60">{job.company}</span>
                    <span className="flex items-center gap-1">
                      <MapPin className="h-3 w-3 opacity-50" />
                      {job.location}
                    </span>
                    {job.remote_type === "full_remote" && (
                      <span className="flex items-center gap-1 text-emerald-400">
                        <Globe className="h-3 w-3" />
                        Remote
                      </span>
                    )}
                  </div>
                </div>

                <div className="shrink-0 text-right hidden sm:block">
                  <span className="text-xs font-mono text-muted-foreground">{job.salary_text}</span>
                  <div className="flex items-center justify-end gap-1 mt-0.5 text-[11px] text-muted-foreground/40">
                    <Clock className="h-3 w-3" />
                    {timeAgo(job.discovered_at)}
                  </div>
                </div>

                <ArrowUpRight className="h-4 w-4 text-white/10 group-hover:text-amber-400 transition-colors shrink-0" />
              </Link>
            ))}
          </div>
        </div>

        {/* Right Column — 2 cols */}
        <div className="lg:col-span-2 space-y-5">
          {/* Pending Actions */}
          <Card className="border-white/[0.06]" style={{ background: "linear-gradient(135deg, rgba(251,191,36,0.02) 0%, transparent 60%)" }}>
            <CardHeader>
              <CardTitle className="text-sm font-semibold flex items-center gap-2">
                <CircleDot className="h-4 w-4 text-amber-400" />
                Actions needed
              </CardTitle>
              <CardAction>
                <span className="font-mono text-[11px] bg-amber-500/10 text-amber-400 px-2 py-0.5 rounded-md">
                  {actions.length}
                </span>
              </CardAction>
            </CardHeader>
            <CardContent className="space-y-1 -mt-1">
              {actions.map((action) => (
                <div
                  key={action.id}
                  className="flex items-start gap-3 rounded-lg px-3 py-3 hover:bg-white/[0.03] transition-colors cursor-pointer"
                >
                  <div className={`mt-2 h-2 w-2 rounded-full shrink-0 ${
                    action.urgency === "high" ? "bg-amber-400 shadow-[0_0_6px_rgba(251,191,36,0.4)]"
                      : action.urgency === "medium" ? "bg-white/30"
                        : "bg-white/10"
                  }`} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold">{action.label}</p>
                    <p className="text-sm text-muted-foreground truncate mt-0.5">{action.target}</p>
                  </div>
                  <span className="text-xs text-muted-foreground shrink-0 mt-0.5">
                    {action.time}
                  </span>
                </div>
              ))}
            </CardContent>
          </Card>

          {/* Quick Import */}
          <div
            className="rounded-xl border border-dashed border-white/[0.08] p-8 text-center hover:border-white/[0.15] transition-colors cursor-pointer group"
            style={{ background: "linear-gradient(135deg, rgba(255,255,255,0.01) 0%, transparent 100%)" }}
          >
            <div className="h-12 w-12 rounded-full bg-white/[0.04] border border-white/[0.06] flex items-center justify-center mx-auto mb-4 group-hover:border-amber-500/20 transition-colors">
              <LinkIcon className="h-5 w-5 text-muted-foreground group-hover:text-amber-400 transition-colors" />
            </div>
            <p className="text-base font-semibold">Quick import</p>
            <p className="text-sm text-muted-foreground mt-1 mb-4">
              Paste a job URL or WhatsApp message
            </p>
            <Button variant="outline" render={<Link href="/dashboard/import" />} nativeButton={false}>
              <Plus className="h-4 w-4" />
              Import now
            </Button>
          </div>

          {/* Pipeline Snapshot */}
          <div className="rounded-xl border border-white/[0.06] p-6" style={{ background: "linear-gradient(135deg, rgba(255,255,255,0.02) 0%, transparent 100%)" }}>
            <div className="flex items-center gap-2 mb-5">
              <Zap className="h-4 w-4 text-amber-400" />
              <span className="text-sm uppercase tracking-[0.12em] text-muted-foreground font-semibold">
                Pipeline
              </span>
            </div>
            <div className="grid grid-cols-3 gap-3">
              {[
                { label: "Review", count: stats.review_queue, color: "text-amber-400", bg: "bg-amber-500/5", border: "border-amber-500/15", glow: "shadow-[0_0_20px_rgba(251,191,36,0.08)]" },
                { label: "Applied", count: stats.applications_sent, color: "text-emerald-400", bg: "bg-emerald-500/5", border: "border-emerald-500/15", glow: "shadow-[0_0_20px_rgba(52,211,153,0.08)]" },
                { label: "Interviews", count: Math.round(stats.applications_sent * stats.interview_rate / 100), color: "text-blue-400", bg: "bg-blue-500/5", border: "border-blue-500/15", glow: "shadow-[0_0_20px_rgba(96,165,250,0.08)]" },
              ].map((stage) => (
                <div
                  key={stage.label}
                  className={`text-center py-6 rounded-xl border ${stage.bg} ${stage.border} ${stage.glow}`}
                >
                  <span className={`font-mono text-3xl font-bold block ${stage.color}`}>
                    {stage.count}
                  </span>
                  <span className="text-sm text-muted-foreground block mt-2 font-medium">
                    {stage.label}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
