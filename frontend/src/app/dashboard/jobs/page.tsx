"use client";

import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
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
  Wifi,
  Flag,
  Loader2,
  Inbox,
  Shield,
} from "lucide-react";
import { useJobs, useShortlistJob, useDismissJob } from "@/hooks/use-api";

const SOURCE_COLORS: Record<string, { dot: string; label: string }> = {
  linkedin: { dot: "bg-blue-500", label: "LinkedIn" },
  adzuna: { dot: "bg-orange-500", label: "Adzuna" },
  indeed: { dot: "bg-violet-500", label: "Indeed" },
  arbeitnow: { dot: "bg-teal-500", label: "Arbeitnow" },
  remoteok: { dot: "bg-emerald-500", label: "RemoteOK" },
  jsearch: { dot: "bg-rose-500", label: "JSearch" },
  google_jobs: { dot: "bg-sky-500", label: "Google" },
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
        <span className="text-[11px] text-muted-foreground/40 font-mono">—</span>
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
  const [remoteFilter, setRemoteFilter] = useState<string | null>(null);
  const [sponsorshipFilter, setSponsorshipFilter] = useState(false);
  const [countryFilter, setCountryFilter] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState("score");

  const { data, isLoading } = useJobs({
    page,
    pageSize: 20,
    roleType: roleFilter,
    country: countryFilter,
    remoteOnly: remoteFilter === "full_remote",
    remoteType: remoteFilter,
    sponsorship: sponsorshipFilter,
    sortBy,
  });

  const shortlist = useShortlistJob();
  const dismiss = useDismissJob();

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

  const activeFilters = [roleFilter, remoteFilter, sponsorshipFilter, countryFilter].filter(Boolean).length;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Inbox</h1>
          <p className="text-xs text-muted-foreground mt-1 font-mono tabular-nums">
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

      {/* Filters */}
      <div className="flex items-center gap-1.5 rounded-lg bg-white/[0.02] border border-white/[0.04] px-2 py-1.5">
        <div className="relative flex-1 max-w-[240px]">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground/40" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search..."
            className="pl-7 h-7 text-xs bg-transparent border-transparent focus:border-white/10 focus:bg-white/[0.02]"
          />
        </div>

        <Separator orientation="vertical" className="h-4 mx-0.5" />

        <Button
          variant={roleFilter === "pm" ? "default" : "ghost"}
          size="xs"
          onClick={() => setRoleFilter(roleFilter === "pm" ? null : "pm")}
          className="font-mono text-[11px]"
        >
          PM
        </Button>

        <Separator orientation="vertical" className="h-4 mx-0.5" />

        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                variant={remoteFilter ? "default" : "ghost"}
                size="xs"
                className="text-[11px]"
              >
                <Wifi className="h-3 w-3" />
                {remoteFilter === "full_remote" ? "Remote" :
                 remoteFilter === "hybrid" ? "Hybrid" :
                 remoteFilter === "onsite" ? "Onsite" :
                 remoteFilter === "unknown" ? "Unknown" : "Work type"}
              </Button>
            }
          />
          <DropdownMenuContent>
            <DropdownMenuItem onClick={() => setRemoteFilter(null)}>
              All
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setRemoteFilter("full_remote")}>
              Remote
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setRemoteFilter("hybrid")}>
              Hybrid
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setRemoteFilter("onsite")}>
              Onsite
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setRemoteFilter("unknown")}>
              Unknown
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                variant={countryFilter ? "default" : "ghost"}
                size="xs"
                className="text-[11px]"
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

        <Button
          variant={sponsorshipFilter ? "default" : "ghost"}
          size="xs"
          onClick={() => setSponsorshipFilter(!sponsorshipFilter)}
          className="text-[11px]"
        >
          <Shield className="h-3 w-3" />
          Visa
        </Button>

        {activeFilters > 0 && (
          <button
            onClick={() => {
              setRoleFilter(null);
              setRemoteFilter(null);
              setSponsorshipFilter(false);
              setCountryFilter(null);
              setSearch("");
            }}
            className="text-[10px] text-amber-400/70 hover:text-amber-400 ml-1 underline underline-offset-2"
          >
            Clear
          </button>
        )}

        <div className="flex-1" />

        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button variant="ghost" size="xs" className="text-[11px]">
                <SlidersHorizontal className="h-3 w-3" />
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

      {/* Job List */}
      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground/50" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-20">
          <Inbox className="h-10 w-10 mx-auto text-white/[0.06] mb-4" />
          <p className="text-sm text-muted-foreground">
            {total === 0
              ? "No jobs discovered yet."
              : "No jobs match your filters."}
          </p>
          {total === 0 && (
            <p className="text-xs text-muted-foreground/50 mt-1">
              Import a job or wait for discovery to run.
            </p>
          )}
        </div>
      ) : (
        <div className="space-y-1.5">
          {filtered.map((job: any) => {
            const score = job.score?.overall_fit ?? null;
            const rolePath = job.score?.role_path;
            const src = SOURCE_COLORS[job.source_name] || SOURCE_COLORS.manual;

            return (
              <Link
                key={job.id}
                href={`/dashboard/jobs/${job.id}`}
                className="group flex items-stretch gap-3 rounded-xl border border-white/[0.04] bg-white/[0.01] px-4 py-3.5 transition-all hover:bg-white/[0.03] hover:border-white/[0.08]"
              >
                {/* Accent edge */}
                <AccentEdge score={score} />

                {/* Score */}
                <ScoreBadge score={score} />

                {/* Main content */}
                <div className="flex-1 min-w-0 flex flex-col justify-center gap-1">
                  {/* Title row */}
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold truncate leading-tight">
                      {job.title}
                    </span>
{/* Role badge removed — single target role */}
                  </div>

                  {/* Meta row */}
                  <div className="flex items-center gap-3 text-sm text-muted-foreground">
                    <span className="font-medium text-foreground/60 truncate max-w-[200px]">
                      {job.company}
                    </span>
                    {job.location && (
                      <span className="flex items-center gap-1 truncate max-w-[200px]">
                        <MapPin className="h-3.5 w-3.5 opacity-50 shrink-0" />
                        {job.location}
                      </span>
                    )}
                    {job.remote_type === "full_remote" && (
                      <span className="flex items-center gap-1 text-emerald-400 shrink-0">
                        <Globe className="h-3.5 w-3.5" />
                        Remote
                      </span>
                    )}
                  </div>
                </div>

                {/* Right side */}
                <div className="flex items-center gap-4 shrink-0">
                  {/* Salary */}
                  {job.salary_text && (
                    <span className="font-mono text-[11px] text-muted-foreground/60 tabular-nums hidden lg:inline">
                      {job.salary_text}
                    </span>
                  )}

                  {/* Source */}
                  <div className="flex items-center gap-1.5">
                    <span className={`h-2 w-2 rounded-full ${src.dot}`} />
                    <span className="text-xs text-muted-foreground">
                      {src.label}
                    </span>
                  </div>

                  {/* Time */}
                  <span className="text-xs text-muted-foreground tabular-nums w-16 text-right">
                    {job.discovered_at ? timeAgo(job.discovered_at) : "—"}
                  </span>

                  {/* Actions (visible on hover) */}
                  <div className="flex items-center gap-0.5 w-16 justify-end opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={(e) => {
                        e.preventDefault();
                        shortlist.mutate(job.id);
                      }}
                      className="p-1.5 rounded-md hover:bg-amber-500/10 text-muted-foreground/40 hover:text-amber-400 transition-colors"
                      title="Shortlist"
                    >
                      <Star className="h-3.5 w-3.5" />
                    </button>
                    <button
                      onClick={(e) => {
                        e.preventDefault();
                        dismiss.mutate(job.id);
                      }}
                      className="p-1.5 rounded-md hover:bg-white/5 text-muted-foreground/40 hover:text-muted-foreground transition-colors"
                      title="Dismiss"
                    >
                      <Archive className="h-3.5 w-3.5" />
                    </button>
                  </div>

                  {/* Arrow (always visible but subtle) */}
                  <ArrowUpRight className="h-4 w-4 text-white/[0.06] group-hover:text-amber-400/60 transition-colors shrink-0" />
                </div>
              </Link>
            );
          })}
        </div>
      )}

      {/* Pagination */}
      {total > 0 && (
        <div className="flex items-center justify-between pt-1">
          <span className="font-mono text-[10px] text-muted-foreground/30 tabular-nums">
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
