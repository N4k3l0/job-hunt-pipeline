"use client";

import { use, useState } from "react";
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
  Briefcase, Star, Sparkles, Loader2, CheckCircle2, AlertCircle,
} from "lucide-react";
import { useJob, useShortlistJob, useGenerateTailored, useDeepScore } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";

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
  const qc = useQueryClient();
  // All hooks must be declared before any early return (Rules of Hooks).
  const [applying, setApplying] = useState(false);
  const [marking, setMarking] = useState(false);

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

  // ── Apply flow ─────────────────────────────────────────────────────────
  // Two distinct user actions, never collapsed:
  //
  //   • "Apply directly" → opens the external posting in a new tab and
  //     does nothing else. The user might find the role doesn't exist, isn't
  //     eligible for their region, or just decides to skip — clicking is
  //     NOT a commitment to apply.
  //
  //   • "I applied" → the user explicitly tells us they actually
  //     submitted. This creates the ApplicationTracking row, flips the
  //     job's own status, and feeds Analytics. Mirrors how the user
  //     actually thinks about their funnel.
  //
  // Popup-blocker note: window.open must happen synchronously inside the
  // click handler, before any await — otherwise browsers silently swallow
  // the new tab.
  const hasUrl = !!(job.apply_url || job.job_url);
  const isAlreadyApplied = job.status === "applied";

  async function handleApply() {
    if (applying) return;
    setApplying(true);
    // Open the new tab synchronously so the popup blocker is happy. We
    // intentionally OMIT the "noopener" feature here — that flag makes
    // window.open return null, which blocks us from rewriting the popup's
    // location after the API call resolves. We sever opener.opener manually
    // once we've navigated, so the security trade-off is the same.
    const popup = window.open("about:blank", "_blank");
    if (popup) {
      // Creative loading state. The resolver chain can take 1–12s on the
      // slow path (Firecrawl + slug-guess + Claude web_search), so a blank
      // tab feels broken. Stages mirror the actual backend pipeline so the
      // copy is honest, with a smooth tween on the progress bar so the
      // user sees forward motion every frame.
      popup.document.write(`<!doctype html>
<html><head><title>Finding posting…</title>
<style>
  :root {
    color-scheme: dark;
    /* Stronger custom ease-out per Emil. Built-in CSS curves lack punch. */
    --ease-out: cubic-bezier(0.23, 1, 0.32, 1);
    --ease-soft: cubic-bezier(0.4, 0, 0.2, 1);
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh;
    display: flex; align-items: center; justify-content: center;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    background: radial-gradient(ellipse 80% 50% at 50% 0%, rgba(251,191,36,0.08), transparent 70%), #0a0a0a;
    color: #fafafa;
    padding: 24px;
  }
  .card {
    width: 100%; max-width: 420px;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 16px;
    padding: 28px;
    background: rgba(255,255,255,0.015);
    box-shadow: 0 24px 48px -16px rgba(0,0,0,0.5);

    /* Card entry: nothing appears from nothing. */
    opacity: 1;
    transform: translateY(0) scale(1);
    transition: opacity 360ms var(--ease-out), transform 360ms var(--ease-out);
  }
  @starting-style {
    .card {
      opacity: 0;
      transform: translateY(8px) scale(0.98);
    }
  }
  .badge {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 4px 10px; border-radius: 999px;
    background: rgba(251,191,36,0.08);
    border: 1px solid rgba(251,191,36,0.2);
    color: #fbbf24; font-size: 11px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.08em;
    margin-bottom: 18px;
  }
  .pulse {
    width: 6px; height: 6px; border-radius: 50%;
    background: #fbbf24;
    /* Transform-based pulse — runs on GPU, can't drop frames under load. */
    animation: pulse 1.4s var(--ease-soft) infinite;
    transform-origin: center;
  }
  @keyframes pulse {
    0%, 100% { transform: scale(1); opacity: 0.55; }
    50%      { transform: scale(1.35); opacity: 1; }
  }
  h1 {
    font-size: 18px; margin: 0 0 6px; font-weight: 600;
    letter-spacing: -0.01em;
  }
  .sub {
    color: #a3a3a3; font-size: 14px; margin: 0 0 22px;
    line-height: 1.5;
  }
  .stage {
    color: #d4d4d4; font-size: 14px; margin-bottom: 14px;
    min-height: 21px; display: flex; align-items: center; gap: 10px;
    transition: color 200ms var(--ease-out);
    /* Stagger entry per stage — set inline below */
    opacity: 1;
    transform: translateY(0);
  }
  @starting-style {
    .stage { opacity: 0; transform: translateY(6px); }
  }
  .stage:nth-child(4) { transition-delay: 0ms; }
  .stage:nth-child(5) { transition-delay: 60ms; }
  .stage:nth-child(6) { transition-delay: 120ms; }
  .stage:nth-child(7) { transition-delay: 180ms; }
  .check {
    position: relative;
    width: 14px; height: 14px; border-radius: 50%;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 9px; flex-shrink: 0;
    /* Specific properties — not 'all'. */
    transition: background-color 200ms var(--ease-out),
                border-color 200ms var(--ease-out);
  }
  .stage.done .check {
    background: rgba(34,197,94,0.15);
    border-color: rgba(34,197,94,0.4);
    color: #4ade80;
  }
  .stage.done .check::before { content: "✓"; }
  .stage.active .check {
    background: rgba(251,191,36,0.15);
    border-color: rgba(251,191,36,0.4);
  }
  .stage.active .check::before {
    content: "";
    position: absolute;
    width: 6px; height: 6px; border-radius: 50%;
    background: #fbbf24;
    /* Scale-pulse > opacity-pulse: GPU, also more 'alive'. */
    animation: dot-pulse 1.2s var(--ease-soft) infinite;
    transform-origin: center;
  }
  @keyframes dot-pulse {
    0%, 100% { transform: scale(1); opacity: 0.7; }
    50%      { transform: scale(1.3); opacity: 1; }
  }
  .bar {
    width: 100%; height: 6px;
    background: rgba(255,255,255,0.05);
    border-radius: 999px; overflow: hidden;
    margin-top: 6px;
  }
  .fill {
    height: 100%;
    background: linear-gradient(90deg, #f59e0b 0%, #fbbf24 50%, #fde047 100%);
    width: 0%; border-radius: 999px;
    transition: width 0.6s var(--ease-out);
    box-shadow: 0 0 12px rgba(251,191,36,0.4);
  }
  .pct {
    font-size: 11px; color: #737373; margin-top: 8px;
    font-variant-numeric: tabular-nums; letter-spacing: 0.04em;
    display: flex; justify-content: space-between;
  }
  .tip {
    margin-top: 18px; padding: 10px 12px;
    background: rgba(255,255,255,0.02);
    border: 1px solid rgba(255,255,255,0.04);
    border-radius: 8px;
    font-size: 12px; color: #a3a3a3;
    line-height: 1.5;
    /* Blur-crossfade for tip text changes — Emil's trick to mask
       the visual gap when one string swaps for another. */
    transition: opacity 220ms var(--ease-out), filter 220ms var(--ease-out);
  }
  .tip.swapping { opacity: 0; filter: blur(2px); }

  @media (prefers-reduced-motion: reduce) {
    .card, .stage, .check, .fill, .tip {
      transition-duration: 0ms !important;
      animation: none !important;
    }
    @starting-style {
      .card, .stage { opacity: 0; transform: none; }
    }
    .pulse, .stage.active .check::before {
      animation: none !important;
    }
  }
</style></head>
<body>
  <div class="card">
    <div class="badge"><div class="pulse"></div> RESOLVING</div>
    <h1>Finding the actual posting</h1>
    <p class="sub">Skipping aggregators — landing you on the company's real apply page.</p>
    <div class="stage active" data-i="0"><div class="check"></div><span>Checking the company's ATS</span></div>
    <div class="stage" data-i="1"><div class="check"></div><span>Scanning the careers page</span></div>
    <div class="stage" data-i="2"><div class="check"></div><span>Verifying with Claude</span></div>
    <div class="stage" data-i="3"><div class="check"></div><span>Opening posting</span></div>
    <div class="bar"><div class="fill" id="fill"></div></div>
    <div class="pct"><span id="pctNum">0%</span><span id="elapsed">0.0s</span></div>
    <div class="tip" id="tip">Most postings resolve in under 3 seconds.</div>
  </div>
<script>
  // Stage timings tuned to the actual backend pipeline. Total budget ~12s.
  // Each stage owns a slice of the progress bar; we tween smoothly between
  // them so the user always sees motion. If the API resolves fast, the
  // popup gets navigated away before the later stages even render.
  var stages = [
    { from: 0,  to: 30, ms: 2000, tip: "Most postings resolve in under 3 seconds." },
    { from: 30, to: 55, ms: 2500, tip: "Aggregator pages need a render — adding ~2s." },
    { from: 55, to: 85, ms: 5500, tip: "Claude is searching the web for the canonical link." },
    { from: 85, to: 96, ms: 1500, tip: "Almost there." },
  ];
  var fill = document.getElementById('fill');
  var pctNum = document.getElementById('pctNum');
  var tipEl = document.getElementById('tip');
  var elapsedEl = document.getElementById('elapsed');
  var startedAt = performance.now();
  var stageEls = document.querySelectorAll('.stage');

  function setStage(i) {
    stageEls.forEach(function (el, idx) {
      el.classList.remove('active', 'done');
      if (idx < i) el.classList.add('done');
      else if (idx === i) el.classList.add('active');
    });
    if (stages[i] && stages[i].tip && stages[i].tip !== tipEl.textContent) {
      // Blur-crossfade: dip out, swap text, fade back in. Emil's trick to
      // mask the visual gap when one string replaces another.
      tipEl.classList.add('swapping');
      setTimeout(function () {
        tipEl.textContent = stages[i].tip;
        tipEl.classList.remove('swapping');
      }, 200);
    }
  }

  function tween(from, to, ms) {
    return new Promise(function (resolve) {
      var t0 = performance.now();
      function frame(now) {
        var p = Math.min(1, (now - t0) / ms);
        // ease-out cubic so it slows toward the end of each stage,
        // making the wait feel less stalled when the API is slow.
        var eased = 1 - Math.pow(1 - p, 3);
        var v = from + (to - from) * eased;
        fill.style.width = v + '%';
        pctNum.textContent = Math.round(v) + '%';
        if (p < 1) requestAnimationFrame(frame); else resolve();
      }
      requestAnimationFrame(frame);
    });
  }

  // 250ms instead of 100ms — a passive elapsed counter doesn't need
  // 10fps updates. Less visual noise, same information.
  setInterval(function () {
    var s = (performance.now() - startedAt) / 1000;
    elapsedEl.textContent = s.toFixed(1) + 's';
  }, 250);

  (async function () {
    for (var i = 0; i < stages.length; i++) {
      setStage(i);
      await tween(stages[i].from, stages[i].to, stages[i].ms);
    }
    // If we're still here after all stages, the API is taking unusually
    // long — keep the bar inching forward so it doesn't look frozen.
    setStage(stages.length - 1);
    var slow = 96;
    setInterval(function () {
      slow = Math.min(99, slow + 0.1);
      fill.style.width = slow + '%';
      pctNum.textContent = Math.round(slow) + '%';
    }, 500);
  })();
</script></body></html>`);
      popup.document.close();
    }
    try {
      const data = await api.post<{ url: string; is_direct_ats: boolean }>(
        `/api/v1/jobs/${id}/apply`,
      );
      if (popup && !popup.closed) {
        // Sever the opener reference so the destination site can't poke
        // back into our tab. Same protection noopener gives, just applied
        // after we're done with the popup.
        try { popup.opener = null; } catch {}
        popup.location.replace(data.url);
      } else {
        // Popup was blocked entirely (ad blockers / strict browser settings)
        // — open in same tab as last resort. Original page is still in
        // history, so back-button gets them home.
        window.open(data.url, "_blank") || (window.location.href = data.url);
      }
    } catch (e: any) {
      // Backend returns 422 with code='no_direct_posting' when the
      // resolver chain (cheap → Firecrawl → slug-guess → Claude) all
      // fail to find a non-aggregator URL. Render a clear failure
      // screen in the popup with manual escape hatches instead of
      // closing it silently.
      const detail = e?.detail || e?.response?.data?.detail;
      const isNoDirect = detail && typeof detail === "object" && detail.code === "no_direct_posting";
      if (popup && !popup.closed && isNoDirect) {
        const company = String(detail.company || "");
        const title = String(detail.title || "");
        const aggUrl = String(detail.aggregator_url || "");
        const careersQ = encodeURIComponent(`${company} careers`);
        popup.document.open();
        popup.document.write(`<!doctype html>
<html><head><title>No direct posting found</title>
<style>
  :root {
    color-scheme: dark;
    --ease-out: cubic-bezier(0.23, 1, 0.32, 1);
  }
  body {
    margin: 0; min-height: 100vh;
    display: flex; align-items: center; justify-content: center;
    font-family: -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
    background: #0a0a0a; color: #fafafa; padding: 24px;
  }
  .card {
    width: 100%; max-width: 460px;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 16px; padding: 28px;
    background: rgba(255,255,255,0.015);
    /* Card entry — same as the resolver card. */
    opacity: 1; transform: translateY(0) scale(1);
    transition: opacity 360ms var(--ease-out), transform 360ms var(--ease-out);
  }
  @starting-style {
    .card { opacity: 0; transform: translateY(8px) scale(0.98); }
  }
  h1 { font-size: 18px; margin: 0 0 8px; font-weight: 600; letter-spacing: -0.01em; }
  p  { color: #a3a3a3; font-size: 14px; line-height: 1.55; margin: 0 0 14px; }
  .role { color: #fafafa; font-weight: 500; }
  a.btn, button.btn {
    display: block; width: 100%; text-align: center;
    padding: 11px 14px; border-radius: 10px;
    font-size: 14px; font-weight: 500; text-decoration: none;
    margin-top: 8px; cursor: pointer; border: 1px solid rgba(255,255,255,0.08);
    background: rgba(255,255,255,0.03); color: #fafafa;
    /* Specific properties — never 'all'. Press feedback via transform. */
    transition: background-color 160ms var(--ease-out),
                border-color 160ms var(--ease-out),
                transform 160ms var(--ease-out);
    will-change: transform;
  }
  a.btn:hover, button.btn:hover {
    background: rgba(255,255,255,0.06);
    border-color: rgba(255,255,255,0.14);
  }
  /* Buttons must feel like they hear the press. */
  a.btn:active, button.btn:active { transform: scale(0.97); }
  a.primary { background: rgba(251,191,36,0.1); border-color: rgba(251,191,36,0.3); color: #fbbf24; }
  a.primary:hover { background: rgba(251,191,36,0.16); }
  .muted { font-size: 12px; color: #737373; margin-top: 14px; text-align: center; }

  @media (prefers-reduced-motion: reduce) {
    .card, a.btn, button.btn { transition: none !important; }
    @starting-style { .card { opacity: 0; transform: none; } }
    a.btn:active, button.btn:active { transform: none; }
  }
</style></head>
<body>
  <div class="card">
    <h1>No direct posting found</h1>
    <p>We searched the company's ATS, careers page, and aggregators, but couldn't verify a direct application URL for <span class="role">${title}</span> at <span class="role">${company}</span>.</p>
    <p>Try one of these to find it manually:</p>
    <a class="btn primary" href="https://www.google.com/search?q=${careersQ}" target="_blank" rel="noopener">Open ${company} careers page</a>
    ${aggUrl ? `<a class="btn" href="${aggUrl}" target="_blank" rel="noopener">View the aggregator listing anyway</a>` : ""}
    <button class="btn" onclick="window.close()">Close</button>
    <p class="muted">If this role really doesn't have a direct apply page, the company may only post via aggregators.</p>
  </div>
</body></html>`);
        popup.document.close();
      } else {
        if (popup && !popup.closed) popup.close();
      }
      const msg = isNoDirect
        ? `No direct posting found for "${detail.title}" at "${detail.company}".`
        : (e?.message || "Couldn't open posting");
      toast.error("Couldn't open posting", { description: msg });
    } finally {
      setApplying(false);
    }
  }

  async function handleMarkApplied() {
    if (marking) return;
    setMarking(true);
    try {
      await api.post(`/api/v1/jobs/${id}/mark-applied`);
      toast.success("Marked as applied", {
        description: "Now tracked in Applications & Analytics.",
      });
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["job", id] });
      qc.invalidateQueries({ queryKey: ["applications"] });
      qc.invalidateQueries({ queryKey: ["analytics"] });
    } catch (e: any) {
      toast.error("Couldn't mark as applied", { description: e?.message });
    } finally {
      setMarking(false);
    }
  }

  async function handleUnmarkApplied() {
    if (marking) return;
    setMarking(true);
    try {
      await api.post(`/api/v1/jobs/${id}/unmark-applied`);
      toast.success("Rolled back", { description: "Application tracking removed." });
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["job", id] });
      qc.invalidateQueries({ queryKey: ["applications"] });
      qc.invalidateQueries({ queryKey: ["analytics"] });
    } catch (e: any) {
      toast.error("Couldn't roll back", { description: e?.message });
    } finally {
      setMarking(false);
    }
  }

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
                <span className="font-mono text-sm text-foreground/80">
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
          {hasUrl && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleApply}
              disabled={applying}
              title="Opens the company's direct ATS posting (Greenhouse, Lever, Ashby, SmartRecruiters) when available — otherwise the source posting. Does NOT mark this as applied."
            >
              {applying ? <Loader2 className="h-4 w-4 animate-spin" /> : <ExternalLink className="h-4 w-4" />}
              {applying ? "Opening…" : "Apply directly"}
            </Button>
          )}
          {/* Explicit tracking toggle — shows different state based on whether
              the job has been marked applied. The user controls this; we
              never auto-set it from a click. */}
          {isAlreadyApplied ? (
            <Button
              variant="outline"
              size="sm"
              onClick={handleUnmarkApplied}
              disabled={marking}
              className="border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/5"
              title="Click to roll back if you didn't actually submit."
            >
              {marking ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
              {marking ? "…" : "Applied ✓"}
            </Button>
          ) : (
            <Button
              variant="outline"
              size="sm"
              onClick={handleMarkApplied}
              disabled={marking}
              title="Press only after you've actually submitted the application. Adds it to your Applications and Analytics."
            >
              {marking ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
              {marking ? "Saving…" : "I applied"}
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
              <CardTitle className="text-base">Job Description</CardTitle>
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
                <CardTitle className="text-base">Requirements & Skills</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {entities.requirements && entities.requirements.length > 0 && (
                  <div>
                    <p className="text-sm text-muted-foreground mb-2 font-medium">Requirements</p>
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
                    <p className="text-sm text-muted-foreground mb-2 font-medium">Skills</p>
                    <div className="flex flex-wrap gap-1.5">
                      {entities.skills.map((s: string, i: number) => (
                        <Badge key={i} variant="secondary" className="text-xs">{s}</Badge>
                      ))}
                    </div>
                  </div>
                )}
                {entities.nice_to_have && entities.nice_to_have.length > 0 && (
                  <div>
                    <p className="text-sm text-muted-foreground mb-2 font-medium">Nice to have</p>
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
              <CardTitle className="text-base">Fit Assessment</CardTitle>
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
                        <span className="text-sm font-medium">Strengths</span>
                      </div>
                      <ul className="space-y-1.5">
                        {score.deep_score.strengths.map((s: string, i: number) => (
                          <li key={i} className="text-sm text-muted-foreground leading-relaxed">
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
                        <span className="text-sm font-medium">Gaps</span>
                      </div>
                      <ul className="space-y-1.5">
                        {score.deep_score.gaps.map((g: string, i: number) => (
                          <li key={i} className="text-sm text-muted-foreground leading-relaxed">
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
                  <p className="text-sm text-muted-foreground mb-3">
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
              <CardTitle className="text-base">Details</CardTitle>
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
