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
  Inbox as InboxIcon, ChevronLeft, ChevronRight, ChevronDown, Check,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useJobs, useFindMoreJobs, useProfile } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";
import { OperationProgress } from "@/components/operation-progress";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { Score, ScoreAxis } from "@/components/ds/score";

// Two-letter ISO codes for the "Europe" saved view. Kept inline so the
// chip works without an extra API trip. Add codes as the matcher expands.
const EUROPE_CODES = new Set([
  "AT","BE","BG","CH","CY","CZ","DE","DK","EE","ES","FI","FR","GB","GR",
  "HR","HU","IE","IS","IT","LI","LT","LU","LV","MT","NL","NO","PL","PT",
  "RO","SE","SI","SK","UK",
]);

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

/** Normalize an axis sub-score (raw 0..max) to a 0–100 percentage so
 *  it can be rendered consistently against the overall_fit scale. */
function pct(raw: number | null | undefined, max: number): number {
  if (raw == null || max <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((raw / max) * 100)));
}

const SORT_LABELS: Record<string, string> = {
  score: "score",
  date: "date",
  salary: "salary",
};

/**
 * Sort dropdown — replaces the native <select> whose popup uses the
 * browser's OS-default style and ignores design tokens. Built on the
 * same Base UI DropdownMenu primitive used in the sidebar, so the
 * popup picks up bg-elev-2 / line / radius / accent like the rest of
 * the app.
 */
function SortMenu({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const current = SORT_LABELS[value] ?? value;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <button
            type="button"
            aria-label="Sort jobs"
            className="ds-mono"
            style={{
              height: 32,
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              background: "var(--ds-bg-elev-1)",
              border: "1px solid var(--ds-line)",
              borderRadius: "var(--ds-r-pill)",
              color: "var(--ds-fg)",
              padding: "0 10px 0 12px",
              fontSize: 12,
              cursor: "pointer",
            }}
          />
        }
      >
        <span style={{ color: "var(--ds-fg-muted)" }}>Sort:</span>
        <span>{current}</span>
        <ChevronDown size={12} strokeWidth={2} style={{ color: "var(--ds-fg-muted)" }} />
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        sideOffset={6}
        className="ds-mono"
        style={{
          minWidth: 140,
          background: "var(--ds-bg-elev-1)",
          border: "1px solid var(--ds-line)",
          borderRadius: "var(--ds-r-card)",
          padding: 4,
          fontSize: 13,
        }}
      >
        {Object.entries(SORT_LABELS).map(([v, label]) => {
          const active = v === value;
          return (
            <DropdownMenuItem
              key={v}
              onSelect={() => onChange(v)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "8px 10px",
                borderRadius: 6,
                color: active ? "var(--ds-accent)" : "var(--ds-fg)",
                cursor: "pointer",
              }}
            >
              <Check
                size={13}
                strokeWidth={2.4}
                style={{ opacity: active ? 1 : 0, color: "var(--ds-accent)" }}
              />
              <span>{label}</span>
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
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

  // ── Saved views (client-side presets) ──────────────────────────────
  // Labels match the Claude Design handoff exactly. "Founding roles"
  // intentionally omitted per request. To add user-defined chips later,
  // append to this list.
  const savedViews: SavedView[] = useMemo(() => [
    {
      id: "top",
      label: "Top matches (≥80)",
      matches: (j) => (j.score?.overall_fit ?? 0) >= 80,
    },
    {
      id: "today",
      label: "New today",
      matches: (j) => {
        if (!j.discovered_at) return false;
        const ageHours = (Date.now() - new Date(j.discovered_at).getTime()) / 3600000;
        return ageHours <= 24;
      },
    },
    {
      id: "remote-us",
      label: "Remote · US",
      matches: (j) =>
        j.remote_type === "full_remote" && (j.country ?? "").toUpperCase() === "US",
    },
    {
      id: "europe",
      label: "Europe",
      matches: (j) => EUROPE_CODES.has((j.country ?? "").toUpperCase()),
    },
    {
      id: "shortlisted",
      label: "Shortlisted",
      matches: (j) => j.status === "shortlisted",
    },
  ], []);

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

  // ── Asymmetric layout split ────────────────────────────────────────
  // Top of the page mirrors the Claude Design prototype:
  //   LEFT  → TopMatchCard (highest-scoring job, with 4-axis breakdown)
  //   RIGHT → "NEXT 5 · ALSO STRONG" panel (jobs #2–#6)
  // Below that lives the "REST OF INBOX · N" dense list (jobs #7+).
  // The top match only earns the editorial treatment when it scored ≥70 —
  // a thin inbox shouldn't have a giant card pointing at a 40-score job.
  const HERO_THRESHOLD = 70;
  const heroEligible = !!filtered[0] && (filtered[0].score?.overall_fit ?? 0) >= HERO_THRESHOLD;
  const topMatch = heroEligible ? filtered[0] : null;
  const nextFive = heroEligible ? filtered.slice(1, 6) : [];
  const rest = heroEligible ? filtered.slice(6) : filtered;

  // ── Optimistic shortlist / unshortlist / dismiss ───────────────────
  const optimisticJobAction = (
    job: any,
    nextStatus: "shortlisted" | "dismissed" | "enriched",
    label: string,
    endpoint: "shortlist" | "unshortlist" | "dismiss",
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
    <div className="ds-root" data-density="comfortable">
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
              className="inbox-chip"
              data-active={activeView === null ? "true" : "false"}
              onClick={() => setActiveView(null)}
            >
              All
            </button>
            {savedViews.map((v) => (
              <button
                key={v.id}
                type="button"
                className="inbox-chip"
                data-active={activeView === v.id ? "true" : "false"}
                onClick={() => setActiveView(activeView === v.id ? null : v.id)}
              >
                {v.label}
              </button>
            ))}

            <div className="ml-auto flex items-center gap-2">
              <SortMenu value={sortBy} onChange={setSortBy} />
            </div>
          </div>
        </div>

        {/* ── Asymmetric top row (TopMatchCard + NEXT 5) ──────────── */}
        {isLoading ? (
          <div className="ds-card" style={{ padding: 60, textAlign: "center", marginTop: 16 }}>
            <Loader2 className="h-6 w-6 animate-spin mx-auto ds-dim" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="ds-card" style={{ padding: 60, textAlign: "center", marginTop: 16, color: "var(--ds-fg-muted)" }}>
            <InboxIcon className="h-7 w-7 mx-auto mb-3 ds-dim" />
            <p style={{ fontSize: 15, color: "var(--ds-fg)", marginBottom: 4 }}>
              No jobs match this view
            </p>
            <p style={{ fontSize: 13 }}>
              Try clearing filters, widening your target countries, or click <span style={{ color: "var(--ds-fg)" }}>Find more jobs</span>.
            </p>
          </div>
        ) : (
          <div className="space-y-5">
            {topMatch && (
              <div
                className="inbox-asym"
                style={{
                  display: "grid",
                  gridTemplateColumns: nextFive.length > 0
                    ? "minmax(0, 1.4fr) minmax(0, 1fr)"
                    : "minmax(0, 1fr)",
                  gap: 18,
                  marginTop: 18,
                }}
              >
                <TopMatchCard
                  job={topMatch}
                  onShortlist={(j) =>
                    j.status === "shortlisted"
                      ? optimisticJobAction(j, "enriched", "Removed from shortlist", "unshortlist")
                      : optimisticJobAction(j, "shortlisted", "Shortlisted", "shortlist")
                  }
                />
                {nextFive.length > 0 && <NextUpPanel jobs={nextFive} />}
              </div>
            )}

            {rest.length > 0 && (
              <div>
                <div
                  className="ds-mono"
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "baseline",
                    padding: "0 4px 10px",
                    fontSize: 10,
                    letterSpacing: "0.1em",
                    color: "var(--ds-fg-dim)",
                    textTransform: "uppercase",
                    marginTop: topMatch ? 24 : 0,
                  }}
                >
                  <span>REST OF INBOX · {rest.length}</span>
                  <span className="ds-faint">SORTED BY {sortBy.toUpperCase()}</span>
                </div>

                <div className="ds-card" style={{ overflow: "hidden" }}>
                  {rest.map((job) => (
                    <DenseRow
                      key={job.id}
                      job={job}
                      onShortlist={(j) =>
                    j.status === "shortlisted"
                      ? optimisticJobAction(j, "enriched", "Removed from shortlist", "unshortlist")
                      : optimisticJobAction(j, "shortlisted", "Shortlisted", "shortlist")
                  }
                      onArchive={(j) => optimisticJobAction(j, "dismissed", "Archived", "dismiss")}
                    />
                  ))}
                </div>
              </div>
            )}

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

        <style>{`
          @media (max-width: 900px) {
            .inbox-asym { grid-template-columns: 1fr !important; }
          }
          /* Filter chips — Claude design spec: 32px tall, 13.5px text. */
          .inbox-chip {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            height: 32px;
            padding: 0 12px;
            background: var(--ds-bg-elev-1);
            border: 1px solid var(--ds-line);
            border-radius: var(--ds-r-pill);
            font-size: 13.5px;
            color: var(--ds-fg-muted);
            cursor: pointer;
            white-space: nowrap;
            transition: all 120ms cubic-bezier(0.32, 0.72, 0.32, 1);
          }
          .inbox-chip:hover {
            color: var(--ds-fg);
            border-color: var(--ds-line-strong);
            background: var(--ds-bg-elev-2);
          }
          .inbox-chip[data-active="true"] {
            background: var(--ds-accent-soft);
            border-color: var(--ds-accent-edge);
            color: var(--ds-accent);
          }
          @media (max-width: 640px) {
            .inbox-chip { height: 44px; padding: 0 14px; font-size: 14px; }
          }
        `}</style>
      </div>
    </div>
  );
}

/* ============================================================
   TopMatchCard — left side of the asymmetric grid.
   Editorial treatment: overline, company, big title, BIG mono
   number (no ring, per request), 4-axis breakdown, action row.
   ============================================================ */
function TopMatchCard({
  job,
  onShortlist,
}: {
  job: any;
  onShortlist: (job: any) => void;
}) {
  const score = job.score?.overall_fit ?? 0;
  return (
    <Link
      href={`/dashboard/jobs/${job.id}`}
      className="ds-editorial-card"
      style={{ textDecoration: "none", padding: 22, display: "block" }}
    >
      <div className="ds-mono" style={{ fontSize: 10, color: "var(--ds-accent)", letterSpacing: "0.12em", marginBottom: 14, textTransform: "uppercase", fontWeight: 600 }}>
        ◆ TOP MATCH · LIVE
      </div>

      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 18 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 13, color: "var(--ds-fg-muted)", fontWeight: 500, marginBottom: 4 }}>
            {job.company}
          </div>
          <h2 style={{
            fontSize: 22,
            fontWeight: 600,
            letterSpacing: "-0.02em",
            margin: 0,
            lineHeight: 1.2,
            color: "var(--ds-fg)",
            textWrap: "balance" as any,
          }}>
            {job.title}
          </h2>
          <div style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            flexWrap: "wrap",
            marginTop: 10,
            fontSize: 13,
            color: "var(--ds-fg-muted)",
          }}>
            {job.location && (
              <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                <MapPin className="h-3 w-3" />
                {job.location}
              </span>
            )}
            {job.salary_text && (
              <span className="ds-mono" style={{ color: "var(--ds-fg)" }}>{job.salary_text}</span>
            )}
            <span className="ds-mono ds-dim">{timeAgo(job.discovered_at)} ago</span>
          </div>
        </div>

        {/* Hero score — mono number, NO ring, slightly bigger than row scores. */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", flexShrink: 0, lineHeight: 1 }}>
          <span
            className="ds-mono ds-s-top"
            style={{
              fontSize: 48,
              fontWeight: 600,
              letterSpacing: "-0.04em",
              lineHeight: 1,
            }}
          >
            {Math.round(score)}
          </span>
          <span className="ds-mono ds-faint" style={{ fontSize: 11, marginTop: 4, letterSpacing: "0.04em" }}>
            /100
          </span>
        </div>
      </div>

      {/* LLM-generated summary — falls back gracefully when deep scoring
          hasn't run yet. Max-width keeps it readable inside the asymmetric
          column without rivaling the title. */}
      {job.score?.summary && (
        <p style={{
          fontSize: 14,
          lineHeight: 1.55,
          color: "var(--ds-fg-muted)",
          margin: "16px 0 0",
          maxWidth: "80ch",
          textWrap: "pretty" as any,
        }}>
          {job.score.summary}
        </p>
      )}

      {/* 4-axis breakdown — only renders if we actually have axis scores.
          The raw axis values are NOT on a 0-100 scale (title maxes at 20,
          skill at 25, seniority at 15, salary at 10 — see backend scorer.py).
          Normalize to a percentage so the bars and the "/100" labels read
          consistently with the rest of the design system. */}
      {job.score && (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
          gap: 14,
          marginTop: 18,
          paddingTop: 16,
          borderTop: "1px solid var(--ds-line)",
        }}>
          <ScoreAxis label="TITLE" value={pct(job.score.title_score, 20)} />
          <ScoreAxis label="SKILLS" value={pct(job.score.skill_score, 25)} />
          <ScoreAxis label="SENIORITY" value={pct(job.score.seniority_score, 15)} />
          <ScoreAxis label="SALARY" value={pct(job.score.salary_score, 10)} />
        </div>
      )}

      {/* Action row */}
      <div
        style={{ display: "flex", gap: 8, marginTop: 18 }}
        onClick={(e) => e.stopPropagation()}
      >
        <span
          className="ds-btn primary"
          style={{ pointerEvents: "none" }}
        >
          <Sparkles className="h-3.5 w-3.5" />
          Open & apply
        </span>
        <button
          type="button"
          className="ds-btn"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onShortlist(job);
          }}
          style={
            job.status === "shortlisted"
              ? { color: "var(--ds-accent)", borderColor: "var(--ds-accent-edge)" }
              : undefined
          }
          aria-pressed={job.status === "shortlisted"}
        >
          <Star
            className="h-3.5 w-3.5"
            fill={job.status === "shortlisted" ? "var(--ds-accent)" : "none"}
            strokeWidth={2}
          />
          {job.status === "shortlisted" ? "Shortlisted" : "Shortlist"}
        </button>
      </div>
    </Link>
  );
}

/* ============================================================
   NextUpPanel — right side of the asymmetric grid.
   Mono overline + 5 compact rows. Small mono number per row,
   not rings, so the side panel doesn't visually fight with
   the TopMatchCard or the dense list below.
   ============================================================ */
function NextUpPanel({ jobs }: { jobs: any[] }) {
  return (
    <div className="ds-card" style={{ padding: 0, overflow: "hidden", display: "flex", flexDirection: "column" }}>
      <div style={{
        padding: "12px 14px",
        borderBottom: "1px solid var(--ds-line-faint)",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
      }}>
        <span
          className="ds-mono"
          style={{
            fontSize: 10,
            color: "var(--ds-fg-faint)",
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            fontWeight: 600,
          }}
        >
          NEXT {jobs.length} · ALSO STRONG
        </span>
      </div>
      <div style={{ flex: 1 }}>
        {jobs.map((job) => (
          <Link
            key={job.id}
            href={`/dashboard/jobs/${job.id}`}
            className="ds-row"
            style={{
              display: "grid",
              gridTemplateColumns: "auto 1fr auto",
              gap: 12,
              alignItems: "center",
              padding: "12px 14px",
              borderTop: "1px solid var(--ds-line-faint)",
              textDecoration: "none",
              minHeight: 56,
            }}
          >
            <Score score={job.score?.overall_fit ?? null} variant="ring" />
            <div style={{ minWidth: 0 }}>
              <div style={{
                fontSize: 13.5,
                fontWeight: 600,
                color: "var(--ds-fg)",
                letterSpacing: "-0.005em",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}>
                {job.title}
              </div>
              <div style={{
                fontSize: 12,
                color: "var(--ds-fg-muted)",
                marginTop: 2,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}>
                {job.company}
                {job.salary_text && (
                  <>
                    <span style={{ color: "var(--ds-fg-faint)", margin: "0 6px" }}>·</span>
                    <span className="ds-mono">{job.salary_text}</span>
                  </>
                )}
              </div>
            </div>
            <span className="ds-mono ds-dim" style={{ fontSize: 11 }}>
              {timeAgo(job.discovered_at)}
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}

/* ============================================================
   DenseRow — the REST OF INBOX list. Uses the ring score
   variant per the user's request (still respects the
   scoreVariant toggle if they switch it).
   ============================================================ */
function DenseRow({
  job,
  onShortlist,
  onArchive,
}: {
  job: any;
  onShortlist: (job: any) => void;
  onArchive: (job: any) => void;
}) {
  return (
    <Link href={`/dashboard/jobs/${job.id}`} className="ds-row">
      <Score score={job.score?.overall_fit ?? null} variant="ring" />

      <div style={{ minWidth: 0 }}>
        <div style={{
          fontWeight: 600,
          fontSize: 14.5,
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
          marginTop: 3,
          flexWrap: "wrap",
          fontSize: 12.5,
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

      <div className="flex items-center" onClick={(e) => e.preventDefault()}>
        <button
          type="button"
          aria-label={job.status === "shortlisted" ? "Shortlisted" : "Shortlist"}
          title={job.status === "shortlisted" ? "Shortlisted" : "Shortlist"}
          className="ds-tap44"
          aria-pressed={job.status === "shortlisted"}
          onClick={(e) => {
            e.preventDefault();
            onShortlist(job);
          }}
          style={{
            width: 36, height: 36,
            display: "inline-flex", alignItems: "center", justifyContent: "center",
            color: job.status === "shortlisted" ? "var(--ds-accent)" : "var(--ds-fg-muted)",
            borderRadius: "var(--ds-r-pill)",
            background: "transparent",
            transition: "all 120ms ease",
          }}
        >
          <Star
            className="h-4 w-4"
            fill={job.status === "shortlisted" ? "var(--ds-accent)" : "none"}
            strokeWidth={2}
          />
        </button>
        <button
          type="button"
          aria-label="Archive"
          title="Archive"
          className="ds-tap44"
          onClick={(e) => {
            e.preventDefault();
            onArchive(job);
          }}
          style={{
            width: 36, height: 36,
            display: "inline-flex", alignItems: "center", justifyContent: "center",
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
  );
}
