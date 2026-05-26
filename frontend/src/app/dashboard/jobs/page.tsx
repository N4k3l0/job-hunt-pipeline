"use client";

/**
 * Inbox — the product's centerpiece.
 *
 * Redesigned 2026-05-26 from the Claude Design handoff
 * (H5t-MvyKb49crrUg7xIebA). The visual layer uses the .ds-* classes
 * defined in design-tokens.css; data wiring + actions are unchanged
 * from the previous version so nothing breaks for existing users.
 *
 * Key visual decisions baked in here (per the chat transcript):
 *   - Asymmetric editorial top-match card + dense list below
 *   - Sticky filter bar with saved-view chips
 *   - 3 score variants (ring / edge / mono), toggled in the local UI
 *   - 2 density modes (comfortable / dense), toggled in the local UI
 *   - Teal accent ONLY for scores ≥80; neutral grays for everything else
 *   - Signature monospace for scores, salaries, counts, time-ago
 *   - 150ms accent edge slides in on row hover; no springs, no glow
 */

import { useState, useMemo } from "react";
import Link from "next/link";
import {
  Search, MapPin, Star, Archive, Plus, Loader2, Sparkles, Linkedin,
  Inbox as InboxIcon, ChevronLeft, ChevronRight, LayoutList, Rows3,
  Circle, BarChart3, Hash,
} from "lucide-react";
import { useJobs, useFindMoreJobs, useProfile } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";
import { OperationProgress } from "@/components/operation-progress";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { Score, ScoreHero, type ScoreVariant } from "@/components/ds/score";

function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return "";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d`;
  return `${Math.floor(days / 7)}w`;
}

type SavedView = {
  id: string;
  label: string;
  matches: (job: any) => boolean;
};

export default function JobsInboxPage() {
  // ── State ──────────────────────────────────────────────────────────
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState("score");

  // New: visual toggles for the design-system tweaks
  const [scoreVariant, setScoreVariant] = useState<ScoreVariant>("ring");
  const [density, setDensity] = useState<"comfortable" | "dense">("comfortable");
  const [activeView, setActiveView] = useState<string | null>(null);

  // ── Data ───────────────────────────────────────────────────────────
  const { data, isLoading } = useJobs({
    page,
    pageSize: 25,
    remoteOnly: false,
    remoteType: null,
    sponsorship: false,
    sortBy,
  });
  const toast = useToast();
  const qc = useQueryClient();
  const findMore = useFindMoreJobs();
  const { data: profile } = useProfile();

  const jobs: any[] = data?.jobs ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / 25) || 1;

  // ── LinkedIn jumping-off URL (preserved from previous version) ─────
  const linkedInSearchUrl = useMemo(() => {
    const roles = (profile?.target_roles || []).slice(0, 3);
    if (roles.length === 0) return null;
    const params = new URLSearchParams();
    params.set("keywords", roles.join(" OR "));
    if (profile?.remote_preference === "full_remote") params.set("f_WT", "2");
    else if (profile?.remote_preference === "hybrid") params.set("f_WT", "3");
    else if (profile?.remote_preference === "onsite") params.set("f_WT", "1");
    params.set("f_TPR", "r604800");
    return `https://www.linkedin.com/jobs/search/?${params.toString()}`;
  }, [profile?.target_roles, profile?.remote_preference]);

  // ── Saved views (client-side, defined per profile) ─────────────────
  // For v1 these are static presets keyed off the data we already have.
  // Later: user can save their own filter combos to chips here.
  const savedViews: SavedView[] = useMemo(() => {
    const views: SavedView[] = [
      { id: "top", label: "Top matches", matches: (j) => (j.score?.overall_fit ?? 0) >= 80 },
      { id: "fresh", label: "New this week", matches: (j) => {
        if (!j.discovered_at) return false;
        const ageDays = (Date.now() - new Date(j.discovered_at).getTime()) / 86400000;
        return ageDays <= 7;
      }},
      { id: "remote", label: "Remote", matches: (j) => j.remote_type === "full_remote" },
      { id: "salary", label: "Has salary", matches: (j) => !!j.salary_text },
    ];
    // Add a chip per preferred country (e.g. "NL only", "DE only")
    for (const code of (profile?.preferred_countries || []).slice(0, 4)) {
      views.push({
        id: `country-${code}`,
        label: `${code} only`,
        matches: (j) => j.country?.toUpperCase() === code.toUpperCase(),
      });
    }
    return views;
  }, [profile?.preferred_countries]);

  // ── Filtering pipeline ─────────────────────────────────────────────
  const filtered = useMemo(() => {
    let out = jobs;
    if (search) {
      const s = search.toLowerCase();
      out = out.filter(
        (j) =>
          j.title?.toLowerCase().includes(s) ||
          j.company?.toLowerCase().includes(s),
      );
    }
    if (activeView) {
      const view = savedViews.find((v) => v.id === activeView);
      if (view) out = out.filter(view.matches);
    }
    return out;
  }, [jobs, search, activeView, savedViews]);

  // ── Top match (for editorial card) + rest ──────────────────────────
  // Pull the highest-scoring job that isn't already shortlisted/dismissed.
  const topMatch = filtered[0];
  const rest = filtered.slice(1);

  // ── Optimistic shortlist / dismiss ─────────────────────────────────
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

  // ── Find more jobs ─────────────────────────────────────────────────
  const handleFindMore = () => {
    findMore.mutate(undefined, {
      onSuccess: (data) => {
        if (data.ingested === 0 && data.found > 0) {
          toast.info("No new jobs found", {
            description: `Found ${data.found} matches but they all already exist in your inbox.`,
          });
        } else if (data.ingested > 0) {
          toast.success(`Added ${data.ingested} new job${data.ingested === 1 ? "" : "s"}`, {
            description: `${data.found} matches found · ${data.duplicates} dedup'd`,
          });
        } else {
          toast.info("No matches found", {
            description: "Try widening your target roles or preferred regions.",
          });
        }
      },
      onError: (err: any) => toast.error("Web search failed", { description: err?.message }),
    });
  };

  // ── Render ─────────────────────────────────────────────────────────
  return (
    <div className="ds-root" data-density={density}>
      <div className="ds-page ds-page-fade">

        {/* ── Header row ─────────────────────────────────────────── */}
        <header className="flex items-end justify-between gap-3 flex-wrap mb-5">
          <div>
            <h1 className="ds-h1">
              Inbox
              {" "}
              <span className="ds-mono ds-faint" style={{ fontSize: 18, fontWeight: 500, letterSpacing: "-0.02em" }}>
                · {total} {filtered.length !== total ? `· ${filtered.length} matching` : ""}
              </span>
            </h1>
            <p className="ds-muted" style={{ fontSize: 13, marginTop: 4 }}>
              Scored against your profile. Top matches highlighted in teal.
            </p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <button
              type="button"
              className="ds-btn"
              onClick={handleFindMore}
              disabled={findMore.isPending}
              title="Searches the open web for jobs that match your profile, then ingests new matches into your inbox. Takes 30–60 seconds."
            >
              {findMore.isPending ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Searching…
                </>
              ) : (
                <>
                  <Sparkles className="h-3.5 w-3.5" />
                  Find more jobs
                </>
              )}
            </button>
            {linkedInSearchUrl && (
              <a
                href={linkedInSearchUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="ds-btn"
                title="Opens LinkedIn's job search with your target roles + remote preference pre-applied, filtered to the past week."
              >
                <Linkedin className="h-3.5 w-3.5" />
                LinkedIn
              </a>
            )}
            <Link href="/dashboard/import" className="ds-btn">
              <Plus className="h-3.5 w-3.5" />
              Import
            </Link>
          </div>
        </header>

        <OperationProgress
          active={findMore.isPending}
          title="Searching the open web for new jobs"
          description="Reading your profile, querying job boards + careers pages, and verifying each match before ingest."
          stages={[
            { label: "Loading your profile", durationMs: 1500, tip: "Reading your target roles, skills, and remote preference." },
            { label: "Searching company careers + ATSes", durationMs: 12000, tip: "Hitting Greenhouse, Lever, Ashby, and niche boards in parallel." },
            { label: "Verifying each posting is open", durationMs: 15000, tip: "Skipping closed listings and aggregator-only hits. Quality > quantity." },
            { label: "Ranking matches by fit", durationMs: 10000, tip: "Aiming for 15–25 high-quality matches, deduplicated against your existing inbox." },
            { label: "Scoring + saving to your inbox", durationMs: 5000, tip: "Each new job scored against your profile so the inbox sort makes sense immediately." },
          ]}
        />

        {/* ── Sticky filter bar ──────────────────────────────────── */}
        <div className="ds-filterbar">
          <div className="flex items-center gap-2 flex-wrap">
            {/* Search */}
            <div className="ds-input" style={{ maxWidth: 280, flex: "1 1 200px" }}>
              <Search className="h-3.5 w-3.5 ds-dim" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search title or company…"
              />
            </div>

            {/* Saved view chips */}
            <button
              type="button"
              className="ds-chip ds-tap44"
              data-active={activeView === null ? "true" : "false"}
              onClick={() => setActiveView(null)}
            >
              All
            </button>
            {savedViews.map((v) => (
              <button
                key={v.id}
                type="button"
                className="ds-chip ds-tap44"
                data-active={activeView === v.id ? "true" : "false"}
                onClick={() => setActiveView(activeView === v.id ? null : v.id)}
              >
                {v.label}
              </button>
            ))}

            {/* Right-side: density + score variant + sort */}
            <div className="ml-auto flex items-center gap-2">
              {/* Density toggle */}
              <div className="inline-flex" style={{ background: "var(--ds-bg-elev-1)", border: "1px solid var(--ds-line)", borderRadius: 8, padding: 2 }}>
                {(["comfortable", "dense"] as const).map((d) => (
                  <button
                    key={d}
                    type="button"
                    onClick={() => setDensity(d)}
                    aria-label={d === "comfortable" ? "Comfortable density" : "Dense density"}
                    title={d === "comfortable" ? "Comfortable density" : "Dense density"}
                    style={{
                      minHeight: 32,
                      width: 32,
                      borderRadius: 6,
                      background: density === d ? "var(--ds-bg-elev-2)" : "transparent",
                      color: density === d ? "var(--ds-fg)" : "var(--ds-fg-muted)",
                      border: density === d ? "1px solid var(--ds-line-strong)" : "1px solid transparent",
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      cursor: "pointer",
                      transition: "all 120ms ease",
                    }}
                  >
                    {d === "comfortable" ? <LayoutList className="h-3.5 w-3.5" /> : <Rows3 className="h-3.5 w-3.5" />}
                  </button>
                ))}
              </div>

              {/* Score variant — small icon segmented */}
              <div className="inline-flex" style={{ background: "var(--ds-bg-elev-1)", border: "1px solid var(--ds-line)", borderRadius: 8, padding: 2 }}>
                {([
                  { v: "ring" as const, icon: <Circle className="h-3.5 w-3.5" />, label: "Ring score" },
                  { v: "edge" as const, icon: <BarChart3 className="h-3.5 w-3.5" />, label: "Edge score" },
                  { v: "mono" as const, icon: <Hash className="h-3.5 w-3.5" />, label: "Mono score" },
                ]).map(({ v, icon, label }) => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => setScoreVariant(v)}
                    aria-label={label}
                    title={label}
                    style={{
                      minHeight: 32,
                      width: 32,
                      borderRadius: 6,
                      background: scoreVariant === v ? "var(--ds-bg-elev-2)" : "transparent",
                      color: scoreVariant === v ? "var(--ds-fg)" : "var(--ds-fg-muted)",
                      border: scoreVariant === v ? "1px solid var(--ds-line-strong)" : "1px solid transparent",
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      cursor: "pointer",
                      transition: "all 120ms ease",
                    }}
                  >
                    {icon}
                  </button>
                ))}
              </div>

              {/* Sort */}
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                aria-label="Sort jobs"
                className="ds-mono"
                style={{
                  height: 36,
                  background: "var(--ds-bg-elev-1)",
                  border: "1px solid var(--ds-line)",
                  borderRadius: "var(--ds-r-pill)",
                  color: "var(--ds-fg)",
                  padding: "0 10px",
                  fontSize: 12,
                  cursor: "pointer",
                }}
              >
                <option value="score">Sort: score</option>
                <option value="date">Sort: date</option>
                <option value="salary">Sort: salary</option>
              </select>
            </div>
          </div>
        </div>

        {/* ── Editorial top match + dense list ───────────────────── */}
        {isLoading ? (
          <div className="ds-card" style={{ padding: 60, textAlign: "center" }}>
            <Loader2 className="h-6 w-6 animate-spin mx-auto ds-dim" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="ds-card" style={{ padding: 60, textAlign: "center", color: "var(--ds-fg-muted)" }}>
            <InboxIcon className="h-7 w-7 mx-auto mb-3 ds-dim" />
            <p style={{ fontSize: 15, color: "var(--ds-fg)", marginBottom: 4 }}>
              No jobs match this view
            </p>
            <p style={{ fontSize: 13 }}>
              Try clearing filters, widening your target countries, or click <span style={{ color: "var(--ds-fg)" }}>Find more jobs</span>.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {topMatch && (topMatch.score?.overall_fit ?? 0) >= 70 && (
              <Link
                href={`/dashboard/jobs/${topMatch.id}`}
                className="ds-editorial-card"
                style={{ textDecoration: "none" }}
              >
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="ds-pill accent" style={{ marginBottom: 10 }}>
                      <Sparkles className="h-3 w-3" />
                      TOP MATCH
                    </div>
                    <h2 className="ds-h2" style={{ marginBottom: 6 }}>
                      {topMatch.title}
                    </h2>
                    <div className="flex items-center gap-3 flex-wrap" style={{ color: "var(--ds-fg-muted)", fontSize: 13 }}>
                      <span style={{ color: "var(--ds-fg)", fontWeight: 500 }}>{topMatch.company}</span>
                      {topMatch.location && (
                        <span className="inline-flex items-center gap-1">
                          <MapPin className="h-3 w-3 ds-dim" />
                          {topMatch.location}
                        </span>
                      )}
                      {topMatch.salary_text && (
                        <span className="ds-mono" style={{ color: "var(--ds-fg)" }}>
                          {topMatch.salary_text}
                        </span>
                      )}
                      <span className="ds-mono ds-dim">
                        {timeAgo(topMatch.discovered_at)} ago
                      </span>
                    </div>
                  </div>
                  <ScoreHero score={topMatch.score?.overall_fit ?? 0} variant={scoreVariant} />
                </div>
              </Link>
            )}

            {/* Dense list — top match excluded if it became the hero */}
            <div className="ds-card" style={{ overflow: "hidden" }}>
              {(topMatch && (topMatch.score?.overall_fit ?? 0) >= 70 ? rest : filtered).map((job) => (
                <Link
                  key={job.id}
                  href={`/dashboard/jobs/${job.id}`}
                  className="ds-row"
                >
                  <Score score={job.score?.overall_fit ?? null} variant={scoreVariant} />

                  <div style={{ minWidth: 0 }}>
                    <div style={{
                      fontWeight: 600,
                      fontSize: density === "dense" ? 13.5 : 14.5,
                      letterSpacing: "-0.01em",
                      color: "var(--ds-fg)",
                      lineHeight: 1.25,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}>
                      {job.title}
                    </div>
                    <div style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 12,
                      marginTop: density === "dense" ? 1 : 3,
                      flexWrap: "wrap",
                      fontSize: density === "dense" ? 12 : 12.5,
                      color: "var(--ds-fg-muted)",
                    }}>
                      <span style={{ color: "var(--ds-fg)", fontWeight: 500 }}>{job.company}</span>
                      {job.location && (
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                          <MapPin className="h-3 w-3 opacity-70" />
                          {job.location}
                        </span>
                      )}
                      {job.salary_text && (
                        <span className="ds-mono" style={{ color: "var(--ds-fg)" }}>{job.salary_text}</span>
                      )}
                      <span className="ds-mono ds-dim" style={{ marginLeft: "auto" }}>
                        {timeAgo(job.discovered_at)}
                      </span>
                    </div>
                  </div>

                  <div
                    className="flex items-center"
                    onClick={(e) => e.preventDefault()}
                  >
                    <button
                      type="button"
                      aria-label="Shortlist"
                      title="Shortlist"
                      className="ds-tap44"
                      onClick={(e) => {
                        e.preventDefault();
                        optimisticJobAction(job, "shortlisted", "Shortlisted", "shortlist");
                      }}
                      style={{
                        width: 36,
                        height: 36,
                        display: "inline-flex",
                        alignItems: "center",
                        justifyContent: "center",
                        color: "var(--ds-fg-muted)",
                        borderRadius: "var(--ds-r-pill)",
                        background: "transparent",
                        transition: "all 120ms ease",
                      }}
                    >
                      <Star className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      aria-label="Archive"
                      title="Archive"
                      className="ds-tap44"
                      onClick={(e) => {
                        e.preventDefault();
                        optimisticJobAction(job, "dismissed", "Archived", "dismiss");
                      }}
                      style={{
                        width: 36,
                        height: 36,
                        display: "inline-flex",
                        alignItems: "center",
                        justifyContent: "center",
                        color: "var(--ds-fg-muted)",
                        borderRadius: "var(--ds-r-pill)",
                        background: "transparent",
                        transition: "all 120ms ease",
                      }}
                    >
                      <Archive className="h-4 w-4" />
                    </button>
                  </div>
                </Link>
              ))}
            </div>

            {/* Pagination */}
            {total > 25 && (
              <div className="flex items-center justify-between" style={{ marginTop: 16 }}>
                <span className="ds-mono ds-muted" style={{ fontSize: 12 }}>
                  Page {page} of {totalPages} · {total} total
                </span>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    className="ds-btn sm"
                    disabled={page <= 1}
                    onClick={() => setPage((p) => p - 1)}
                  >
                    <ChevronLeft className="h-3.5 w-3.5" />
                    Prev
                  </button>
                  <button
                    type="button"
                    className="ds-btn sm"
                    disabled={page >= totalPages}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    Next
                    <ChevronRight className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
