"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, ExternalLink, Loader2, SkipForward, ThumbsDown, ThumbsUp, Undo2 } from "lucide-react";
import { useRateJob, useRatingQueue, useRatingResults, useUnrateJob } from "@/hooks/use-api";
import type { JobRatingValue, JobToRate, RatedJobScores, RatingResults, ScoringMetrics } from "@/lib/types";

const PAGE = 10;
// Matches the backend's MIN_RATINGS_FOR_RESULTS.
const MIN_FOR_RESULTS = 20;

type Action = JobRatingValue | "skip";

const REMOTE_LABELS: Record<string, string> = { full_remote: "Remote", hybrid: "Hybrid", onsite: "On-site" };
const LEVEL_LABELS: Record<string, string> = {
  entry: "Entry level", mid: "Mid level", senior: "Senior", lead: "Lead",
  director: "Director", vp: "VP", c_level: "C-level",
};

function salary(job: JobToRate) {
  if (job.salary_text) return job.salary_text;
  const { salary_min: min, salary_max: max } = job;
  if (!min && !max) return null;
  const range = min && max ? `${min.toLocaleString()}–${max.toLocaleString()}` : (min ?? max)!.toLocaleString();
  return `${job.salary_currency ?? ""} ${range}`.trim();
}

function posted(iso: string | null) {
  if (!iso) return null;
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days < 1) return "Posted today";
  if (days === 1) return "Posted yesterday";
  return `Posted ${days} days ago`;
}

function JobCard({ job }: { job: JobToRate }) {
  const facts = [
    job.location,
    job.remote_type ? REMOTE_LABELS[job.remote_type] : null,
    job.seniority ? LEVEL_LABELS[job.seniority] ?? job.seniority : null,
    salary(job),
    posted(job.posted_at),
  ].filter(Boolean) as string[];
  return (
    <div className="space-y-4">
      <div>
        <div className="ds-muted" style={{ fontSize: 13 }}>{job.company}</div>
        <h2 className="ds-h2" style={{ marginTop: 2 }}>{job.title}</h2>
        {facts.length > 0 && (
          <div className="flex flex-wrap" style={{ gap: 6, marginTop: 10 }}>
            {facts.map((fact) => <span key={fact} className="ds-pill">{fact}</span>)}
          </div>
        )}
      </div>
      {job.skills.length > 0 && (
        <div>
          <div className="ds-dim" style={{ fontSize: 12, marginBottom: 6 }}>Skills the job asks for</div>
          <div className="flex flex-wrap" style={{ gap: 6 }}>
            {job.skills.map((skill) => <span key={skill} className="ds-pill">{skill}</span>)}
          </div>
        </div>
      )}
      {job.requirements.length > 0 && (
        <ul className="ds-muted" style={{ fontSize: 13, paddingLeft: 18, listStyle: "disc", display: "grid", gap: 4 }}>
          {job.requirements.map((requirement) => <li key={requirement}>{requirement}</li>)}
        </ul>
      )}
      {job.description && (
        <p
          className="ds-muted"
          style={{
            fontSize: 13, lineHeight: 1.6, maxHeight: 260, overflowY: "auto",
            paddingTop: 12, borderTop: "1px solid var(--ds-line)",
          }}
        >
          {job.description}
        </p>
      )}
      {job.job_url && (
        <a href={job.job_url} target="_blank" rel="noopener noreferrer" className="ds-btn ghost sm" style={{ paddingLeft: 0 }}>
          Open the full posting <ExternalLink className="h-3.5 w-3.5" />
        </a>
      )}
    </div>
  );
}

const METRIC_ROWS: {
  label: string;
  value: (m: ScoringMetrics) => string;
  // Higher is better unless marked otherwise; used to highlight the better column.
  rank: (m: ScoringMetrics) => number | null;
}[] = [
  {
    label: "Good fits among the 10 highest scores",
    value: (m) => `${m.top.good} of ${m.top.size}`,
    rank: (m) => (m.top.size ? m.top.good / m.top.size : null),
  },
  {
    label: "Inbox jobs (score 50+) that are good fits",
    value: (m) => (m.inbox.size ? `${m.inbox.good} of ${m.inbox.size} (${Math.round((100 * m.inbox.good) / m.inbox.size)}%)` : "None in the inbox"),
    rank: (m) => (m.inbox.size ? m.inbox.good / m.inbox.size : null),
  },
  {
    label: "Good fits kept out of the inbox",
    value: (m) => String(m.missed_good),
    rank: (m) => -m.missed_good,
  },
  {
    label: "Scores a good fit above a not-for-me job",
    value: (m) => (m.ranking_accuracy === null ? "Rate both kinds first" : `${Math.round(m.ranking_accuracy * 100)}% of the time`),
    rank: (m) => m.ranking_accuracy,
  },
];

function Disagreements({ title, rows, versions }: { title: string; rows: RatedJobScores[]; versions: string[] }) {
  if (!rows.length) return null;
  return (
    <div className="space-y-2">
      <h3 className="ds-h3" style={{ fontSize: 14 }}>{title}</h3>
      <div className="ds-card" style={{ overflow: "hidden" }}>
        {rows.map((row) => (
          <div
            key={row.job_id}
            className="flex items-center justify-between"
            style={{ gap: 12, padding: "10px 14px", borderTop: "1px solid var(--ds-line)" }}
          >
            <div className="min-w-0">
              <div className="truncate" style={{ fontSize: 13, fontWeight: 500 }}>{row.title}</div>
              <div className="ds-dim truncate" style={{ fontSize: 12 }}>{row.company}</div>
            </div>
            <div className="ds-mono ds-muted" style={{ fontSize: 12, whiteSpace: "nowrap" }}>
              {versions.map((v) => Math.round(row.scores[v])).join(" → ")}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Results({ results }: { results: RatingResults }) {
  const columns = [
    { label: "Scoring now", metrics: results.current },
    ...(results.proposed ? [{ label: "New scoring", metrics: results.proposed }] : []),
  ];
  const versions = columns.map((c) => String(c.metrics.version));
  return (
    <section className="space-y-4">
      <div>
        <h2 className="ds-h3">How the scores agree with you</h2>
        <p className="ds-muted" style={{ fontSize: 13, marginTop: 4, maxWidth: 620 }}>
          Based on the {results.rated} jobs you rated ({results.good} good fits).
          {results.proposed && " Both columns score the same jobs with today's details. Your inbox keeps the current scoring until the new one is switched on."}
        </p>
      </div>
      <div className="ds-card" style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse", minWidth: 420 }}>
          <thead>
            <tr className="ds-dim" style={{ fontSize: 12, textAlign: "left" }}>
              <th style={{ padding: "10px 14px", fontWeight: 500 }} />
              {columns.map((c) => (
                <th key={c.label} style={{ padding: "10px 14px", fontWeight: 500 }}>{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {METRIC_ROWS.map((row) => {
              const ranks = columns.map((c) => row.rank(c.metrics));
              const best = columns.length > 1 && ranks.every((r) => r !== null) && ranks[0] !== ranks[1]
                ? (ranks[1]! > ranks[0]! ? 1 : 0)
                : -1;
              return (
                <tr key={row.label} style={{ borderTop: "1px solid var(--ds-line)" }}>
                  <td className="ds-muted" style={{ padding: "10px 14px" }}>{row.label}</td>
                  {columns.map((c, i) => (
                    <td
                      key={c.label}
                      className="ds-mono"
                      style={{ padding: "10px 14px", color: i === best ? "var(--ds-accent)" : undefined, fontWeight: i === best ? 600 : 400 }}
                    >
                      {row.value(c.metrics)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <Disagreements
        title={results.proposed ? "Good fits the new scoring keeps out of the inbox" : "Good fits kept out of the inbox"}
        rows={results.disagreements.good_scored_low}
        versions={versions}
      />
      <Disagreements
        title={results.proposed ? "Not-for-me jobs the new scoring still lets in" : "Not-for-me jobs in the inbox"}
        rows={results.disagreements.bad_scored_high}
        versions={versions}
      />
    </section>
  );
}

export default function RateMatchesPage() {
  // What the user did with each job this visit, and the order they did it in.
  const [handled, setHandled] = useState<Record<string, Action>>({});
  const [history, setHistory] = useState<JobToRate[]>([]);
  // Jobs brought back by Undo, shown before the rest.
  const [returned, setReturned] = useState<JobToRate[]>([]);

  const skipped = Object.values(handled).filter((a) => a === "skip").length;
  const { data, isLoading, isError, isFetching, refetch } = useRatingQueue(Math.min(50, PAGE + skipped));
  const rate = useRateJob();
  const unrate = useUnrateJob();

  const seen = new Set<string>();
  const pending = [...returned, ...(data?.jobs ?? [])].filter((j) => {
    if (handled[j.id] || seen.has(j.id)) return false;
    seen.add(j.id);
    return true;
  });
  const job = pending[0];
  const rated = data?.rated ?? 0;
  const target = data?.target ?? 50;
  const results = useRatingResults(rated >= MIN_FOR_RESULTS);

  const act = (action: Action) => {
    if (!job) return;
    const remaining = pending.length - 1;
    setHandled((h) => ({ ...h, [job.id]: action }));
    setHistory((h) => [...h, job]);
    setReturned((r) => r.filter((j) => j.id !== job.id));
    if (action !== "skip") {
      // Refill once the rating is saved, so the next page leaves it out.
      rate.mutate({ jobId: job.id, rating: action }, { onSuccess: () => { if (remaining <= 3) refetch(); } });
    }
  };

  const undo = () => {
    const last = history[history.length - 1];
    if (!last || rate.isPending) return;
    const action = handled[last.id];
    setHistory((h) => h.slice(0, -1));
    setHandled((h) => {
      const next = { ...h };
      delete next[last.id];
      return next;
    });
    setReturned((r) => [last, ...r.filter((j) => j.id !== last.id)]);
    if (action !== "skip") unrate.mutate(last.id);
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (event.metaKey || event.ctrlKey || event.altKey || target?.closest("input, textarea, select")) return;
      const key = event.key.toLowerCase();
      if (key === "g") act("good");
      else if (key === "n") act("bad");
      else if (key === "s") act("skip");
      else if (key === "u") undo();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className="ds-root ds-page-fade" style={{ background: "var(--ds-bg)" }}>
      <div className="space-y-6" style={{ maxWidth: 760, margin: "0 auto" }}>
        <div>
          <h1 className="ds-h1">Rate matches</h1>
          <p className="ds-muted" style={{ marginTop: 6, maxWidth: 620 }}>
            Say whether each job fits you. Scores are hidden so they don&apos;t sway you. Your ratings show how well
            the app&apos;s scoring agrees with you, and let changes to it be tested on your answers first. Ratings
            don&apos;t hide or move jobs in your inbox.
          </p>
        </div>

        <div className="space-y-2">
          <div className="flex items-baseline justify-between" style={{ gap: 12 }}>
            <span style={{ fontSize: 13 }}>
              <span className="ds-mono" style={{ fontWeight: 600 }}>{rated}</span>
              <span className="ds-muted"> of {target} rated</span>
            </span>
            <span className="ds-dim" style={{ fontSize: 12 }}>About 15 minutes for {target}</span>
          </div>
          <div style={{ height: 4, borderRadius: 2, background: "var(--ds-line)", overflow: "hidden" }}>
            <div
              style={{
                height: "100%", width: `${Math.min(100, (100 * rated) / target)}%`,
                background: "var(--ds-accent)", transition: "width 200ms ease",
              }}
            />
          </div>
        </div>

        {isLoading ? (
          <div className="flex justify-center py-16"><Loader2 className="h-6 w-6 animate-spin ds-dim" /></div>
        ) : isError ? (
          <div className="ds-card ds-muted" style={{ padding: 20, fontSize: 14 }}>
            Couldn&apos;t load jobs to rate. <button type="button" className="ds-btn ghost sm" onClick={() => refetch()}>Try again</button>
          </div>
        ) : job ? (
          <div className="ds-card" style={{ padding: 20 }}>
            <JobCard key={job.id} job={job} />
            <div
              className="flex flex-wrap items-center justify-between"
              style={{ gap: 10, marginTop: 20, paddingTop: 16, borderTop: "1px solid var(--ds-line)" }}
            >
              <button type="button" className="ds-btn ghost sm" onClick={undo} disabled={!history.length || rate.isPending}>
                <Undo2 className="h-3.5 w-3.5" /> Undo <kbd className="ds-dim ds-mono hidden sm:inline">U</kbd>
              </button>
              <div className="flex flex-wrap" style={{ gap: 8 }}>
                <button type="button" className="ds-btn" onClick={() => act("skip")} title="Can't tell">
                  <SkipForward className="h-4 w-4" /> Skip <kbd className="ds-dim ds-mono hidden sm:inline">S</kbd>
                </button>
                <button type="button" className="ds-btn" onClick={() => act("bad")}>
                  <ThumbsDown className="h-4 w-4" /> Not for me <kbd className="ds-dim ds-mono hidden sm:inline">N</kbd>
                </button>
                <button type="button" className="ds-btn primary" onClick={() => act("good")}>
                  <ThumbsUp className="h-4 w-4" /> Good fit <kbd className="ds-mono hidden sm:inline" style={{ opacity: 0.6 }}>G</kbd>
                </button>
              </div>
            </div>
          </div>
        ) : isFetching || rate.isPending ? (
          <div className="flex justify-center py-16"><Loader2 className="h-6 w-6 animate-spin ds-dim" /></div>
        ) : (
          <div className="ds-card" style={{ padding: 24, textAlign: "center" }}>
            <CheckCircle2 className="h-6 w-6 mx-auto" style={{ color: "var(--ds-accent)" }} />
            <div style={{ fontWeight: 600, marginTop: 8 }}>No more jobs to rate right now</div>
            <p className="ds-muted" style={{ fontSize: 13, marginTop: 4 }}>
              New matches show up here as the app finds them.{" "}
              <Link href="/dashboard/jobs" className="underline">Go to your inbox</Link>
            </p>
          </div>
        )}

        {rated < MIN_FOR_RESULTS ? (
          <p className="ds-dim" style={{ fontSize: 13 }}>
            Rate {MIN_FOR_RESULTS - rated} more {MIN_FOR_RESULTS - rated === 1 ? "job" : "jobs"} to see how the scores agree with you.
          </p>
        ) : results.data ? (
          <Results results={results.data} />
        ) : results.isLoading ? (
          <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin ds-dim" /></div>
        ) : null}
      </div>
    </div>
  );
}
