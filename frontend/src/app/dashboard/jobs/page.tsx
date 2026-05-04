"use client";

import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Search,
  MapPin,
  Globe,
  ArrowUpRight,
  Star,
  Archive,
  ChevronLeft,
  ChevronRight,
  SlidersHorizontal,
  Plus,
  Flag,
  Loader2,
  Inbox,
  Database,
} from "lucide-react";
import { useJobs } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";

const SOURCE_COLORS: Record<string, { dot: string; label: string }> = {
  linkedin: { dot: "bg-blue-500", label: "LinkedIn" },
  adzuna: { dot: "bg-orange-500", label: "Adzuna" },
  indeed: { dot: "bg-violet-500", label: "Indeed" },
  arbeitnow: { dot: "bg-teal-500", label: "Arbeitnow" },
  remoteok: { dot: "bg-emerald-500", label: "RemoteOK" },
  jsearch: { dot: "bg-rose-500", label: "JSearch" },
  google_jobs: { dot: "bg-sky-500", label: "Google" },
  himalayas: { dot: "bg-fuchsia-500", label: "Himalayas" },
  remotive: { dot: "bg-cyan-500", label: "Remotive" },
  weworkremotely: { dot: "bg-indigo-500", label: "WeWorkRemotely" },
  crossover: { dot: "bg-lime-500", label: "Crossover" },
  dailyremote: { dot: "bg-pink-500", label: "DailyRemote" },
  manual: { dot: "bg-amber-500/60", label: "Manual" },
};

function timeAgo(dateStr: string) {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return `${Math.floor(days / 7)}w ago`;
}

function ScoreBadge({ score }: { score: number | null }) {
  if (score === null || score === undefined || score === 0) {
    return (
      <div className="w-10 h-10 rounded-lg bg-white/[0.03] border border-white/[0.05] flex items-center justify-center">
        <span className="text-base text-muted-foreground font-mono">—</span>
      </div>
    );
  }

  const bg =
    score >= 80
      ? "bg-emerald-500/10 border-emerald-500/25 shadow-[0_0_12px_rgba(52,211,153,0.08)]"
      : score >= 60
        ? "bg-amber-500/10 border-amber-500/25 shadow-[0_0_12px_rgba(251,191,36,0.08)]"
        : "bg-white/[0.03] border-white/[0.06]";
  const text =
    score >= 80
      ? "text-emerald-400"
      : score >= 60
        ? "text-amber-400"
        : "text-muted-foreground";

  return (
    <div className={`w-10 h-10 rounded-lg border flex items-center justify-center ${bg}`}>
      <span className={`font-mono text-sm font-bold tabular-nums ${text}`}>{score}</span>
    </div>
  );
}

function AccentEdge({ score }: { score: number | null }) {
  if (!score || score < 40) return <div className="w-[2px] self-stretch rounded-full bg-white/[0.03]" />;

  const color =
    score >= 80
      ? "bg-gradient-to-b from-emerald-500/60 to-emerald-500/10"
      : score >= 60
        ? "bg-gradient-to-b from-amber-500/60 to-amber-500/10"
        : "bg-gradient-to-b from-white/10 to-transparent";

  return <div className={`w-[2px] self-stretch rounded-full ${color}`} />;
}

export default function JobsInboxPage() {
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<string | null>(null);
  const [countryFilter, setCountryFilter] = useState<string | null>(null);
  const [sourceFilter, setSourceFilter] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState("score");

  // Work-type filter is gone — profile's `remote_preference` already
  // enforces remote intent server-side. The Visa toggle was also removed:
  // very few sources publish a sponsorship flag, so the filter returned 0
  // jobs in practice — misleading. Sponsorship signal can come back as a
  // JD-text heuristic later, but we won't surface a UI control until the
  // data is real.
  const { data, isLoading } = useJobs({
    page,
    pageSize: 20,
    roleType: roleFilter,
    country: countryFilter,
    remoteOnly: false,
    remoteType: null,
    sponsorship: false,
    source: sourceFilter,
    sortBy,
  });

  const toast = useToast();
  const qc = useQueryClient();

  /**
   * Apply an optimistic status change to the cached job list, then commit (or
   * roll back) after the toast's undo window. We call the network directly
   * instead of via `useMutation` so the request can be cancelled inside the
   * 5-second window without leaving a stale mutation in flight.
   */
  const optimisticJobAction = (
    job: any,
    nextStatus: "shortlisted" | "dismissed",
    label: string,
    endpoint: "shortlist" | "dismiss",
  ) => {
    const queryKeys = qc.getQueryCache().findAll({ queryKey: ["jobs"] });
    const snapshots = queryKeys.map((q) => ({ key: q.queryKey, data: q.state.data }));

    const patch = (data: any) => {
      if (!data?.jobs) return data;
      return {
        ...data,
        jobs: data.jobs.map((j: any) =>
          j.id === job.id ? { ...j, status: nextStatus } : j,
        ),
      };
    };
    queryKeys.forEach((q) => {
      qc.setQueryData(q.queryKey, (old: any) => patch(old));
    });

    toast.action({
      message: label,
      description: job.title ? `${job.company} — ${job.title}` : undefined,
      actionLabel: "Undo",
      duration: 5000,
      onCommit: async () => {
        try {
          await api.post(`/api/v1/jobs/${job.id}/${endpoint}`);
        } catch (err: any) {
          snapshots.forEach((s) => qc.setQueryData(s.key, s.data));
          toast.error(`Couldn't ${endpoint}`, { description: err?.message });
        } finally {
          qc.invalidateQueries({ queryKey: ["jobs"] });
        }
      },
      onUndo: () => {
        snapshots.forEach((s) => qc.setQueryData(s.key, s.data));
      },
    });
  };

  const jobs = data?.jobs ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / 20) || 1;

  const filtered = search
    ? jobs.filter(
        (j: any) =>
          j.title?.toLowerCase().includes(search.toLowerCase()) ||
          j.company?.toLowerCase().includes(search.toLowerCase())
      )
    : jobs;

  const activeFilters = [roleFilter, countryFilter, sourceFilter].filter(Boolean).length;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-end justify-between">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight">Inbox</h1>
          <p className="text-sm text-muted-foreground mt-1 font-mono tabular-nums">
            {total} jobs
            {activeFilters > 0 && ` · ${filtered.length} matching`}
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          render={<Link href="/dashboard/import" />}
          nativeButton={false}
        >
          <Plus className="h-3.5 w-3.5" />
          Import
        </Button>
      </div>

      {/* Filters — stacks on mobile, inline on tablet+ */}
      <div className="rounded-lg bg-white/[0.02] border border-white/[0.04] p-2 space-y-2 sm:space-y-0 sm:flex sm:items-center sm:gap-1.5">
        <div className="relative w-full sm:max-w-[240px]">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search company or title…"
            className="pl-8 h-10 sm:h-9 text-sm bg-transparent border-transparent focus:border-white/10 focus:bg-white/[0.02]"
          />
        </div>

        <div className="flex items-center gap-1.5 overflow-x-auto -mx-1 px-1 sm:contents">
        <Separator orientation="vertical" className="h-4 mx-0.5 hidden sm:block" />

        {/* Role filter is driven by the user's profile target_roles — the
            inbox is already pre-filtered, so a hardcoded PM chip here would
            force the wrong query for an AI-only user. If we ever need a
            quick role switcher we'll surface one based on target_roles. */}

        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                variant={countryFilter ? "default" : "ghost"}
                size="sm"
                className="text-sm"
              >
                <Flag className="h-3 w-3" />
                {countryFilter || "Region"}
              </Button>
            }
          />
          <DropdownMenuContent>
            <DropdownMenuItem onClick={() => setCountryFilter(null)}>
              All regions
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setCountryFilter("US")}>
              United States
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setCountryFilter("CA")}>
              Canada
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setCountryFilter("GB")}>
              United Kingdom
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setCountryFilter("DE")}>
              Germany
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setCountryFilter("FR")}>
              France
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                variant={sourceFilter ? "default" : "ghost"}
                size="sm"
                className="text-sm"
              >
                <Database className="h-3 w-3" />
                {sourceFilter ? (SOURCE_COLORS[sourceFilter]?.label ?? sourceFilter) : "Source"}
              </Button>
            }
          />
          <DropdownMenuContent align="start">
            <DropdownMenuItem onClick={() => setSourceFilter(null)}>
              All sources
            </DropdownMenuItem>
            {Object.entries(SOURCE_COLORS).map(([key, meta]) => (
              <DropdownMenuItem
                key={key}
                onClick={() => setSourceFilter(key)}
                className="flex items-center gap-2"
              >
                <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} />
                {meta.label}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        {activeFilters > 0 && (
          <button
            onClick={() => {
              setRoleFilter(null);
              setCountryFilter(null);
              setSourceFilter(null);
              setSearch("");
            }}
            className="text-sm text-amber-400 hover:text-amber-300 ml-1 underline underline-offset-2"
          >
            Clear
          </button>
        )}

        <div className="flex-1" />

        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button variant="ghost" size="sm" className="text-sm">
                <SlidersHorizontal className="h-3.5 w-3.5" />
                Sort
              </Button>
            }
          />
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => setSortBy("score")}>
              By score
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setSortBy("date")}>
              By date
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setSortBy("salary")}>
              By salary
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        </div>
      </div>

      {/* Job List */}
      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground/50" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-20">
          <Inbox className="h-10 w-10 mx-auto text-white/[0.15] mb-4" />
          <p className="text-base text-muted-foreground">
            {total === 0
              ? "No jobs discovered yet."
              : "No jobs match your filters."}
          </p>
          {total === 0 && (
            <p className="text-sm text-muted-foreground mt-2">
              Import a job or wait for discovery to run.
            </p>
          )}
        </div>
      ) : (
        <div className="space-y-1.5">
          {filtered.map((job: any) => {
            const score = job.score?.overall_fit ?? null;
            const src = SOURCE_COLORS[job.source_name] || SOURCE_COLORS.manual;

            return (
              <Link
                key={job.id}
                href={`/dashboard/jobs/${job.id}`}
                className="group relative flex items-start gap-3 rounded-xl border border-white/[0.04] bg-white/[0.01] px-3 py-3 sm:px-4 sm:py-3.5 transition-all hover:bg-white/[0.03] hover:border-white/[0.08]"
              >
                <AccentEdge score={score} />
                <ScoreBadge score={score} />

                {/* Main content — always shown, wraps gracefully on mobile */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-sm font-semibold leading-snug line-clamp-2 sm:truncate">
                      {job.title}
                    </span>
                    {/* Action buttons: always visible on touch, fade in on hover for desktop */}
                    <div className="flex items-center gap-0.5 shrink-0 opacity-100 sm:opacity-40 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={(e) => {
                          e.preventDefault();
                          optimisticJobAction(job, "shortlisted", "Shortlisted", "shortlist");
                        }}
                        className="p-2 sm:p-1.5 -my-1 rounded-md hover:bg-amber-500/10 text-muted-foreground/60 hover:text-amber-400 transition-colors"
                        aria-label="Shortlist"
                      >
                        <Star className="h-4 w-4 sm:h-3.5 sm:w-3.5" />
                      </button>
                      <button
                        onClick={(e) => {
                          e.preventDefault();
                          optimisticJobAction(job, "dismissed", "Dismissed", "dismiss");
                        }}
                        className="p-2 sm:p-1.5 -my-1 rounded-md hover:bg-white/5 text-muted-foreground/60 hover:text-muted-foreground transition-colors"
                        aria-label="Dismiss"
                      >
                        <Archive className="h-4 w-4 sm:h-3.5 sm:w-3.5" />
                      </button>
                      <ArrowUpRight className="hidden sm:block h-4 w-4 ml-1 text-white/[0.08] group-hover:text-amber-400/60 transition-colors" />
                    </div>
                  </div>

                  {/* Meta row 1: company always shown, prominent */}
                  <div className="text-sm sm:text-base font-medium text-foreground/85 truncate mt-0.5">
                    {job.company}
                  </div>

                  {/* Meta row 2: chips that wrap; everything visible on every screen */}
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1.5 text-sm text-muted-foreground">
                    {job.location && (
                      <span className="inline-flex items-center gap-1 min-w-0">
                        <MapPin className="h-3.5 w-3.5 opacity-70 shrink-0" />
                        <span className="truncate max-w-[180px]">{job.location}</span>
                      </span>
                    )}
                    {job.remote_type === "full_remote" && (
                      <span className="inline-flex items-center gap-1 text-emerald-400">
                        <Globe className="h-3.5 w-3.5" />
                        Remote
                      </span>
                    )}
                    {job.salary_text && (
                      <span className="font-mono tabular-nums text-foreground/80">
                        {job.salary_text}
                      </span>
                    )}
                    <span className="inline-flex items-center gap-1">
                      <span className={`h-1.5 w-1.5 rounded-full ${src.dot}`} />
                      <span className="text-muted-foreground">{src.label}</span>
                    </span>
                    {job.discovered_at && (
                      <span className="text-muted-foreground tabular-nums ml-auto sm:ml-0">
                        {timeAgo(job.discovered_at)}
                      </span>
                    )}
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      )}

      {/* Pagination */}
      {total > 0 && (
        <div className="flex items-center justify-between pt-1">
          <span className="font-mono text-sm text-muted-foreground tabular-nums">
            Page {page} of {totalPages} · {total} total
          </span>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon-xs"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="icon-xs"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
