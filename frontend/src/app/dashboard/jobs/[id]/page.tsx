"use client";

import { use } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import {
  Card, CardContent, CardHeader, CardTitle, CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  ArrowLeft, MapPin, Globe, Building2, Clock, ExternalLink,
  Briefcase, Star, Sparkles, Loader2, CheckCircle2, AlertCircle, Search,
} from "lucide-react";
import { useJob, useShortlistJob, useGenerateTailored, useDeepScore } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";

function ScoreRing({ score, size = 56 }: { score: number; size?: number }) {
  const strokeWidth = 4;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;
  const color = score >= 85 ? "#34d399" : score >= 70 ? "#fbbf24" : "#6b7280";

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="currentColor" strokeWidth={strokeWidth} className="text-white/[0.04]" />
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeDasharray={circumference} strokeDashoffset={offset} />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center font-mono text-sm font-bold tabular-nums">{score}</span>
    </div>
  );
}

export default function JobDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: job, isLoading, error } = useJob(id);
  const shortlist = useShortlistJob();
  const generateTailored = useGenerateTailored();
  const deepScore = useDeepScore();
  const toast = useToast();
  const router = useRouter();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error || !job) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" size="sm" render={<Link href="/dashboard/jobs" />}>
          <ArrowLeft className="h-4 w-4" /> Back to inbox
        </Button>
        <p className="text-muted-foreground">Job not found.</p>
      </div>
    );
  }

  const score = job.score;
  const entities = job.entities;
  const overallFit = score?.overall_fit ?? 0;

  // ── Apply destination ──────────────────────────────────────────────────
  // We collapsed "View posting" and "Find direct apply" into a single
  // primary "Apply directly" button that smart-routes:
  //
  //   1. If we already have a URL on a known free ATS (Greenhouse, Lever,
  //      Ashby, Workable, SmartRecruiters, Jobvite, Recruitee, BambooHR,
  //      Breezy, Workday, TeamTailor) — use it directly. One click, no
  //      signup wall.
  //   2. Otherwise — open a Google search across those ATSes for
  //      "<company>" "<title>". The same job is almost always mirrored
  //      on the company's own ATS page, signup-free.
  //
  // The aggregator URL (RemoteOK / LinkedIn / Adzuna / etc.) is intentionally
  // dropped from the UI: it sends the user to a signup wall, which is the
  // problem this button exists to solve.
  const ATS_HOST_PATTERNS = [
    /(^|\.)greenhouse\.io$/i,
    /(^|\.)lever\.co$/i,
    /(^|\.)ashbyhq\.com$/i,
    /(^|\.)workable\.com$/i,
    /(^|\.)smartrecruiters\.com$/i,
    /(^|\.)jobvite\.com$/i,
    /(^|\.)recruitee\.com$/i,
    /(^|\.)bamboohr\.com$/i,
    /(^|\.)breezy\.hr$/i,
    /(^|\.)myworkdayjobs\.com$/i,
    /(^|\.)teamtailor\.com$/i,
    /(^|\.)icims\.com$/i,
    /(^|\.)pinpointhq\.com$/i,
  ];
  const isAtsUrl = (raw: string | null | undefined): boolean => {
    if (!raw) return false;
    try {
      const host = new URL(raw).hostname;
      return ATS_HOST_PATTERNS.some((re) => re.test(host));
    } catch {
      return false;
    }
  };

  const atsSearchHref = (() => {
    const company = (job.company ?? "").trim();
    const title = (job.title ?? "").trim();
    if (!company || !title) return null;
    const sites = [
      "site:boards.greenhouse.io",
      "site:job-boards.greenhouse.io",
      "site:jobs.lever.co",
      "site:jobs.ashbyhq.com",
      "site:apply.workable.com",
      "site:jobs.smartrecruiters.com",
      "site:jobs.jobvite.com",
      "site:recruitee.com",
      "site:bamboohr.com",
      "site:breezy.hr",
      "site:myworkdayjobs.com",
    ].join(" OR ");
    const q = `(${sites}) "${company}" "${title}"`;
    return `https://www.google.com/search?q=${encodeURIComponent(q)}`;
  })();

  // Prefer an existing ATS link (apply_url first — that's the
  // "click to apply" target — then the canonical job_url). Fall back to
  // the ATS search when nothing direct is available.
  const directAtsLink = [job.apply_url, job.job_url].find(isAtsUrl) || null;
  const applyHref = directAtsLink ?? atsSearchHref;
  const applyIsDirect = !!directAtsLink;

  return (
    <div className="space-y-6 max-w-4xl">
      {/* Back */}
      <Button variant="ghost" size="sm" render={<Link href="/dashboard/jobs" />}>
        <ArrowLeft className="h-4 w-4" /> Back to inbox
      </Button>

      {/* Header — meta on top, actions below; both rows wrap cleanly on phone */}
      <div className="space-y-4">
        <div className="flex items-start gap-4 sm:gap-5">
          {score && <ScoreRing score={overallFit} />}
          <div className="flex-1 min-w-0">
            <h1 className="font-display text-2xl sm:text-3xl font-semibold tracking-tight leading-snug">{job.title}</h1>
            <div className="flex items-center flex-wrap gap-x-4 gap-y-1 mt-1.5 text-sm text-muted-foreground">
              <span className="flex items-center gap-1.5">
                <Building2 className="h-4 w-4 opacity-50" />
                {job.company}
              </span>
              {job.location && (
                <span className="flex items-center gap-1.5">
                  <MapPin className="h-4 w-4 opacity-50" />
                  {job.location}
                </span>
              )}
              {job.remote_type === "full_remote" && (
                <span className="flex items-center gap-1.5 text-emerald-400">
                  <Globe className="h-4 w-4" />
                  Remote
                </span>
              )}
              {job.salary_text && (
                <span className="font-mono text-xs text-muted-foreground/80">
                  {job.salary_text}
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              shortlist.mutate(id, {
                onSuccess: () => toast.success("Shortlisted"),
                onError: (e: any) => toast.error("Couldn't shortlist", { description: e?.message }),
              })
            }
          >
            <Star className="h-4 w-4" /> Shortlist
          </Button>
          {applyHref && (
            <Button
              variant="outline"
              size="sm"
              nativeButton={false}
              title={applyIsDirect
                ? "This posting is on a free ATS — apply directly, no signup."
                : "Searches Greenhouse/Lever/Ashby/Workable for the same role on the company's own ATS."}
              render={<a href={applyHref} target="_blank" rel="noopener noreferrer" />}
            >
              {applyIsDirect ? <ExternalLink className="h-4 w-4" /> : <Search className="h-4 w-4" />}
              {applyIsDirect ? "Apply directly" : "Find direct apply"}
            </Button>
          )}
          <Button
            size="sm"
            onClick={() =>
              generateTailored.mutate(id, {
                onSuccess: () => {
                  toast.success("Tailoring started", {
                    description: "Live progress in the Review Queue.",
                  });
                  router.push("/dashboard/review");
                },
                onError: (e: any) => toast.error("Couldn't queue tailoring", { description: e?.message }),
              })
            }
            disabled={generateTailored.isPending}
          >
            {generateTailored.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {generateTailored.isPending ? "Generating…" : "Generate application"}
          </Button>
        </div>
      </div>

      {generateTailored.isSuccess && (
        <div className="flex items-center gap-2 text-sm text-emerald-400 bg-emerald-500/5 border border-emerald-500/10 rounded-lg px-4 py-3">
          <CheckCircle2 className="h-4 w-4" />
          Tailored application is being generated. Check the Review Queue shortly.
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-3">
        {/* Left: Description — 2 cols */}
        <div className="lg:col-span-2 space-y-5">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Job Description</CardTitle>
            </CardHeader>
            <CardContent>
              {job.raw_description ? (
                <div
                  className="text-sm leading-relaxed text-foreground/80 prose prose-invert prose-sm max-w-none
                    [&_h2]:text-sm [&_h2]:font-semibold [&_h2]:mt-4 [&_h2]:mb-2
                    [&_h3]:text-sm [&_h3]:font-medium [&_h3]:mt-3 [&_h3]:mb-1
                    [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:space-y-1
                    [&_p]:mb-2 [&_a]:text-amber-400 [&_a]:underline"
                  dangerouslySetInnerHTML={{ __html: job.raw_description }}
                />
              ) : (
                <p className="text-sm text-muted-foreground">No description available.</p>
              )}
            </CardContent>
          </Card>

          {entities && ((entities.skills?.length ?? 0) > 0 || (entities.requirements?.length ?? 0) > 0) && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Requirements & Skills</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {entities.requirements && entities.requirements.length > 0 && (
                  <div>
                    <p className="text-xs text-muted-foreground mb-2">Requirements</p>
                    <ul className="space-y-1">
                      {entities.requirements.map((r: string, i: number) => (
                        <li key={i} className="text-sm flex items-start gap-2">
                          <span className="text-muted-foreground/30 mt-1">-</span> {r}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {entities.skills && entities.skills.length > 0 && (
                  <div>
                    <p className="text-xs text-muted-foreground mb-2">Skills</p>
                    <div className="flex flex-wrap gap-1.5">
                      {entities.skills.map((s: string, i: number) => (
                        <Badge key={i} variant="secondary" className="text-xs">{s}</Badge>
                      ))}
                    </div>
                  </div>
                )}
                {entities.nice_to_have && entities.nice_to_have.length > 0 && (
                  <div>
                    <p className="text-xs text-muted-foreground mb-2">Nice to have</p>
                    <div className="flex flex-wrap gap-1.5">
                      {entities.nice_to_have.map((s: string, i: number) => (
                        <Badge key={i} variant="outline" className="text-xs">{s}</Badge>
                      ))}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </div>

        {/* Right: Score + Meta — 1 col */}
        <div className="space-y-5">
          {/* Deep Score / AI Assessment */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Fit Assessment</CardTitle>
              <CardDescription>
                {score?.deep_score ? "AI-powered resume vs job analysis" : "Get a detailed fit analysis"}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {score?.deep_score ? (
                <>
                  {/* Score is already shown as the ring in the page header — show
                      only the recommendation badge here to avoid duplication. */}
                  <Badge
                    variant="secondary"
                    className={`text-xs self-start ${
                      score.deep_score.recommendation === "strong_apply"
                        ? "bg-emerald-500/10 text-emerald-400"
                        : score.deep_score.recommendation === "apply"
                          ? "bg-amber-500/10 text-amber-400"
                          : score.deep_score.recommendation === "maybe"
                            ? "bg-orange-500/10 text-orange-400"
                            : "bg-red-500/10 text-red-400"
                    }`}
                  >
                    {score.deep_score.recommendation === "strong_apply" ? "Strong Apply" :
                     score.deep_score.recommendation === "apply" ? "Apply" :
                     score.deep_score.recommendation === "maybe" ? "Maybe" : "Skip"}
                  </Badge>

                  {/* Summary */}
                  <p className="text-sm text-muted-foreground leading-relaxed">
                    {score.deep_score.summary}
                  </p>

                  <Separator />

                  {/* Strengths */}
                  {score.deep_score.strengths?.length > 0 && (
                    <div>
                      <div className="flex items-center gap-1.5 mb-2">
                        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                        <span className="text-xs font-medium">Strengths</span>
                      </div>
                      <ul className="space-y-1.5">
                        {score.deep_score.strengths.map((s: string, i: number) => (
                          <li key={i} className="text-xs text-muted-foreground leading-relaxed">
                            {s}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Gaps */}
                  {score.deep_score.gaps?.length > 0 && (
                    <div>
                      <div className="flex items-center gap-1.5 mb-2">
                        <AlertCircle className="h-3.5 w-3.5 text-amber-400" />
                        <span className="text-xs font-medium">Gaps</span>
                      </div>
                      <ul className="space-y-1.5">
                        {score.deep_score.gaps.map((g: string, i: number) => (
                          <li key={i} className="text-xs text-muted-foreground leading-relaxed">
                            {g}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-xs w-full"
                    onClick={() =>
                      deepScore.mutate(id, {
                        onSuccess: () => toast.success("Fit analysis updated"),
                        onError: (e: any) => toast.error("Analysis failed", { description: e?.message }),
                      })
                    }
                    disabled={deepScore.isPending}
                  >
                    {deepScore.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                    Re-analyze
                  </Button>
                </>
              ) : (
                <div className="text-center py-4">
                  <p className="text-xs text-muted-foreground mb-3">
                    Compare your resume against this job posting
                  </p>
                  <Button
                    size="sm"
                    onClick={() =>
                      deepScore.mutate(id, {
                        onSuccess: () => toast.success("Fit analysis updated"),
                        onError: (e: any) => toast.error("Analysis failed", { description: e?.message }),
                      })
                    }
                    disabled={deepScore.isPending}
                  >
                    {deepScore.isPending ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Sparkles className="h-3.5 w-3.5" />
                    )}
                    {deepScore.isPending ? "Analyzing..." : "Analyze fit"}
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              {job.employment_type && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Type</span>
                  <span className="capitalize">{job.employment_type?.replace("_", " ")}</span>
                </div>
              )}
              {job.seniority && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Seniority</span>
                  <span className="capitalize">{job.seniority}</span>
                </div>
              )}
              {job.country && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Country</span>
                  <span>{job.country}</span>
                </div>
              )}
              {entities?.sponsorship_available !== null && entities?.sponsorship_available !== undefined && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Visa sponsorship</span>
                  <span>{entities.sponsorship_available ? "Yes" : "No"}</span>
                </div>
              )}
              {job.discovered_at && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Discovered</span>
                  <span className="font-mono text-xs">{new Date(job.discovered_at).toLocaleDateString()}</span>
                </div>
              )}
            </CardContent>
          </Card>

        </div>
      </div>
    </div>
  );
}
