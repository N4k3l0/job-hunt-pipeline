"use client";

import { use, useEffect, useState } from "react";
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
  Briefcase, Star, Sparkles, Loader2, CheckCircle2, AlertCircle, Send,
} from "lucide-react";
import {
  useJob, useShortlistJob, useGenerateTailored, useDeepScore, usePrepareAutoApplication,
} from "@/hooks/use-api";
import { AUTO_APPLY_STATUS_LABELS } from "@/components/auto-apply-status";
import { ScoreHero, ScoreAxis } from "@/components/ds/score";
import { useToast } from "@/components/ui/toast";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { OperationProgress } from "@/components/operation-progress";

/** Normalize an axis sub-score (raw 0..max) to a 0–100 percentage so
 *  the bars render consistently against the overall_fit scale. Each
 *  axis has a different max in the backend scorer (title 20, skill 25,
 *  seniority 15, industry 10, geo 15, remote 5, salary 10, visa 10). */
function pct(raw: number | null | undefined, max: number): number {
  if (raw == null || max <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((raw / max) * 100)));
}

function ScoreRing({ score, size = 56 }: { score: number; size?: number }) {
  const strokeWidth = 4;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;
  const color = score >= 85 ? "#34d399" : score >= 70 ? "#fbbf24" : "#6b7280";

  // Spring-style entrance: ring sweeps from empty to its target value once
  // on mount, and the number counts up to match. Single occurrence per page
  // (the score ring lives on the detail header only — the inbox uses
  // ScoreBadge which we leave un-animated since it renders N times per row,
  // and per Emil's frequency rule, repeated UI shouldn't animate on every
  // appearance).
  const [animOffset, setAnimOffset] = useState(circumference);
  const [displayScore, setDisplayScore] = useState(0);

  useEffect(() => {
    // Two RAFs to make sure the initial value paints before we transition.
    const raf1 = requestAnimationFrame(() => {
      const raf2 = requestAnimationFrame(() => setAnimOffset(offset));
      return () => cancelAnimationFrame(raf2);
    });
    // Number count-up over 700ms with strong ease-out.
    const start = performance.now();
    const duration = 700;
    let frame: number;
    function tick(now: number) {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplayScore(Math.round(score * eased));
      if (t < 1) frame = requestAnimationFrame(tick);
    }
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf1);
      cancelAnimationFrame(frame);
    };
    // Run only when the score itself changes — re-render ≠ re-animate.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [score]);

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="currentColor" strokeWidth={strokeWidth} className="text-white/[0.04]" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={animOffset}
          style={{ transition: "stroke-dashoffset 800ms cubic-bezier(0.23, 1, 0.32, 1)" }}
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center font-mono text-sm font-bold tabular-nums">
        {displayScore}
      </span>
    </div>
  );
}


export default function JobDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: job, isLoading, error } = useJob(id);
  const shortlist = useShortlistJob();
  const generateTailored = useGenerateTailored();
  const deepScore = useDeepScore();
  const prepareApplication = usePrepareAutoApplication();
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
    <div class="stage" data-i="2"><div class="check"></div><span>Verifying the link</span></div>
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
    { from: 55, to: 85, ms: 5500, tip: "Searching the web for the canonical link." },
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
      // Client-side timeout matches the backend's 45s asyncio.wait_for.
      // Without this, a dropped Vercel connection (e.g. function killed
      // at the 60s ceiling before our wait_for could fire) would leave
      // the fetch promise hanging indefinitely — user staring at a fake
      // loading popup for minutes. AbortController fires after 50s so
      // the catch block runs and the popup gets a clear failure card.
      const controller = new AbortController();
      const abortTimer = setTimeout(() => controller.abort(), 50_000);
      let data: { url: string; is_direct_ats: boolean };
      try {
        data = await api.post<{ url: string; is_direct_ats: boolean }>(
          `/api/v1/jobs/${id}/apply`,
          undefined,
          { signal: controller.signal },
        );
      } finally {
        clearTimeout(abortTimer);
      }
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
      // Also handle client-side abort (50s timeout) the same way —
      // user shouldn't sit on a fake loading bar forever when the
      // backend has clearly exceeded its budget.
      const isAbort = e?.name === "AbortError" || /aborted|timeout/i.test(String(e?.message || ""));
      const detail = e?.detail || e?.response?.data?.detail;
      const isNoDirect = isAbort || (detail && typeof detail === "object" && detail.code === "no_direct_posting");
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
      // useJob caches under ["jobs", id] (plural) — mark-applied was
      // invalidating the singular key, so the detail UI never reflected
      // the new tracking status until a hard refresh.
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["jobs", id] });
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
      qc.invalidateQueries({ queryKey: ["jobs", id] });
      qc.invalidateQueries({ queryKey: ["applications"] });
      qc.invalidateQueries({ queryKey: ["analytics"] });
    } catch (e: any) {
      toast.error("Couldn't roll back", { description: e?.message });
    } finally {
      setMarking(false);
    }
  }

  return (
    <div className="ds-root ds-page-fade" style={{ background: "var(--ds-bg)" }}>
      <div className="space-y-6" style={{ maxWidth: 1100, margin: "0 auto" }}>
      {/* Back — uses ds-btn ghost */}
      <Link href="/dashboard/jobs" className="ds-btn ghost" style={{ paddingLeft: 0, alignSelf: "flex-start", width: "fit-content" }}>
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to inbox
      </Link>

      {/* Editorial header: company over title, structured meta pills,
          hero score on the right. Asymmetric per the design. */}
      <div className="space-y-4">
        <div className="flex items-start gap-4 sm:gap-6 flex-wrap">
          <div className="flex-1 min-w-0">
            <div className="ds-muted" style={{ fontSize: 14, fontWeight: 500, letterSpacing: "-0.005em" }}>
              {job.company}
            </div>
            <h1 className="ds-h1" style={{ marginTop: 4, textWrap: "balance" }}>
              {(job as any).title_en || job.title}
            </h1>
            <div className="flex flex-wrap" style={{ gap: 8, marginTop: 12 }}>
              {job.location && (
                <span className="ds-pill">
                  <MapPin className="h-3 w-3 opacity-70" />
                  {job.location}
                </span>
              )}
              {job.remote_type === "full_remote" && (
                <span className="ds-pill accent">
                  <Globe className="h-3 w-3" />
                  Remote
                </span>
              )}
              {job.salary_text && (
                <span className="ds-pill">
                  <span className="ds-mono">{job.salary_text}</span>
                </span>
              )}
              {job.linkedin_alert && (
                <span
                  className="ds-pill"
                  title={`Your LinkedIn job alert sent this ${job.linkedin_alert.times_sent === 1 ? "once" : `${job.linkedin_alert.times_sent} times`}`}
                >
                  From your LinkedIn alert
                  {job.linkedin_alert.search ? `: ${job.linkedin_alert.search}` : ""}
                </span>
              )}
            </div>
          </div>
          {score && (
            <ScoreHero score={overallFit} variant="ring" />
          )}
        </div>
        {/* Primary action row — ds-btn buttons, primary CTA in teal */}
        <div className="flex flex-wrap items-center" style={{ gap: 8, marginTop: 22 }}>
          {hasUrl && (
            <button
              type="button"
              className="ds-btn primary"
              onClick={handleApply}
              disabled={applying}
              title="Opens the company's direct ATS posting when available."
            >
              {applying ? <Loader2 className="h-4 w-4 animate-spin" /> : <ExternalLink className="h-4 w-4" />}
              {applying ? "Opening…" : "Apply directly"}
            </button>
          )}
          {job.auto_apply?.application_id ? (
            <Link href={`/dashboard/auto-apply/${job.auto_apply.application_id}`} className="ds-btn">
              <Send className="h-4 w-4" />
              Apply for me: {AUTO_APPLY_STATUS_LABELS[job.auto_apply.status ?? "preparing"]}
            </Link>
          ) : job.auto_apply?.supported && !isAlreadyApplied ? (
            <button
              type="button"
              className="ds-btn"
              onClick={() =>
                prepareApplication.mutate(id, {
                  onSuccess: (application) => router.push(`/dashboard/auto-apply/${application.id}`),
                  onError: (e) => toast.error("Couldn't prepare the application", { description: e.message }),
                })
              }
              disabled={prepareApplication.isPending}
              title="Fills in the company's application form from your profile. You check it before anything is sent."
            >
              {prepareApplication.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              {prepareApplication.isPending ? "Preparing…" : "Apply for me"}
            </button>
          ) : null}
          <button
            type="button"
            className="ds-btn"
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
            {generateTailored.isPending ? "Generating…" : "Tailor application"}
          </button>
          <button
            type="button"
            className="ds-btn"
            onClick={() =>
              shortlist.mutate(id, {
                onSuccess: () => toast.success("Shortlisted"),
                onError: (e: any) => toast.error("Couldn't shortlist", { description: e?.message }),
              })
            }
          >
            <Star className="h-4 w-4" />
            Shortlist
          </button>
          {isAlreadyApplied ? (
            <button
              type="button"
              className="ds-btn"
              onClick={handleUnmarkApplied}
              disabled={marking}
              style={{ color: "var(--ds-accent)", borderColor: "var(--ds-accent-edge)" }}
              title="Click to roll back if you didn't actually submit."
            >
              {marking ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
              {marking ? "…" : "Applied"}
            </button>
          ) : (
            <button
              type="button"
              className="ds-btn ghost"
              onClick={handleMarkApplied}
              disabled={marking}
              title="Press only after you've actually submitted the application."
            >
              {marking ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
              {marking ? "Saving…" : "I applied"}
            </button>
          )}
        </div>
        <OperationProgress
          active={prepareApplication.isPending}
          title="Preparing your application"
          stages={[
            { label: "Reading the application form", durationMs: 2000, tip: "Every question the company asks, straight from its hiring system." },
            { label: "Filling in from your profile", durationMs: 1000, tip: "Contact details, resume, work rights." },
            { label: "Drafting answers to the rest", durationMs: 9000, tip: "Only from your real experience. You check each one." },
          ]}
        />
      </div>

      {generateTailored.isSuccess && (
        <div className="ds-card" style={{
          display: "flex", alignItems: "center", gap: 10,
          padding: "10px 14px",
          background: "var(--ds-accent-soft)",
          borderColor: "var(--ds-accent-edge)",
          color: "var(--ds-accent)",
          fontSize: 13,
        }}>
          <CheckCircle2 className="h-4 w-4" />
          Tailored application is being generated. Check the Review Queue shortly.
        </div>
      )}

      {/* Two-column body: main content + sticky score-breakdown sidebar */}
      <div className="grid gap-7 lg:grid-cols-[minmax(0,1fr)_320px]" style={{ marginTop: 4 }}>

        {/* ── LEFT COLUMN ── */}
        <div className="space-y-6 min-w-0">

          {/* "Why this matched you" — only when deep_score has run */}
          {score?.deep_score?.summary && (
            <section>
              <div className="ds-mono ds-faint" style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase" }}>
                Why this matched you
              </div>
              <p style={{
                fontSize: 14.5, lineHeight: 1.65, marginTop: 8,
                color: "var(--ds-fg)", maxWidth: "65ch",
              }}>
                {score.deep_score.summary}
              </p>
              {score.deep_score.recommendation && (
                <div className="ds-pill accent" style={{ marginTop: 12 }}>
                  {score.deep_score.recommendation === "strong_apply" ? "Strong Apply" :
                   score.deep_score.recommendation === "apply" ? "Apply" :
                   score.deep_score.recommendation === "maybe" ? "Maybe" : "Skip"}
                </div>
              )}
            </section>
          )}

          {/* Strengths / Gaps grid — design's two-column treatment */}
          {(score?.deep_score?.strengths?.length || score?.deep_score?.gaps?.length) && (
            <div className="grid gap-5 sm:grid-cols-2">
              {score.deep_score.strengths?.length > 0 && (
                <div>
                  <div className="ds-mono ds-faint" style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase" }}>
                    Strengths
                  </div>
                  <ul style={{ listStyle: "none", padding: 0, margin: "10px 0 0", display: "flex", flexDirection: "column", gap: 8 }}>
                    {score.deep_score.strengths.map((s: string, i: number) => (
                      <li key={i} style={{ display: "flex", gap: 10, fontSize: 13, lineHeight: 1.55, color: "var(--ds-fg)" }}>
                        <CheckCircle2 className="h-3.5 w-3.5" style={{ color: "var(--ds-accent)", flexShrink: 0, marginTop: 2 }} />
                        <span>{s}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {score.deep_score.gaps?.length > 0 && (
                <div>
                  <div className="ds-mono ds-faint" style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase" }}>
                    Gaps
                  </div>
                  <ul style={{ listStyle: "none", padding: 0, margin: "10px 0 0", display: "flex", flexDirection: "column", gap: 8 }}>
                    {score.deep_score.gaps.map((g: string, i: number) => (
                      <li key={i} style={{ display: "flex", gap: 10, fontSize: 13, lineHeight: 1.55, color: "var(--ds-fg-muted)" }}>
                        <span style={{ color: "var(--ds-fg-dim)", fontSize: 16, lineHeight: 1, marginTop: 2 }}>·</span>
                        <span>{g}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* Trigger / re-run deep score */}
          {!score?.deep_score && (
            <div className="ds-card" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 12, alignItems: "flex-start" }}>
              <div>
                <h3 className="ds-h3">Get a deeper fit analysis</h3>
                <p className="ds-muted" style={{ fontSize: 13, marginTop: 4 }}>
                  Compares your full resume against this posting and tells you exactly where you match and where you stretch.
                </p>
              </div>
              <button
                type="button"
                className="ds-btn primary"
                onClick={() =>
                  deepScore.mutate(id, {
                    onSuccess: () => toast.success("Fit analysis updated"),
                    onError: (e: any) => toast.error("Analysis failed", { description: e?.message }),
                  })
                }
                disabled={deepScore.isPending}
              >
                {deepScore.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                {deepScore.isPending ? "Analyzing…" : "Analyze fit"}
              </button>
            </div>
          )}

          <OperationProgress
            active={deepScore.isPending}
            stages={[
              { label: "Loading your profile", durationMs: 800, tip: "Pulling work history, skills, education." },
              { label: "Reading the job description", durationMs: 1200, tip: "Parsing requirements + nice-to-haves." },
              { label: "Cross-referencing your background", durationMs: 3500, tip: "Where you match, where you stretch." },
              { label: "Drafting the recommendation", durationMs: 3000, tip: "Apply / Maybe / Skip — with reasoning." },
            ]}
          />

          {/* About the role + Requirements. The backend sends the
              description sanitized, in English when the posting was
              translated; a small badge says when it's a translation. Job
              boards write these descriptions, so never render
              raw_description or raw_description_en as HTML. */}
          <section>
            <h3 className="ds-h3">About the role</h3>
            {(() => {
              const translated = !!job.raw_description_en;
              const body = job.description_html;
              if (!body) {
                return (
                  <p className="ds-muted" style={{ fontSize: 13, marginTop: 12 }}>
                    No description available.
                  </p>
                );
              }
              return (
                <>
                  {translated && (
                    <div
                      className="ds-mono"
                      style={{
                        marginTop: 10,
                        fontSize: 11,
                        letterSpacing: "0.08em",
                        textTransform: "uppercase",
                        color: "var(--ds-fg-muted)",
                      }}
                      title="The original posting was in another language. Showing an English translation."
                    >
                      · Translated to English
                    </div>
                  )}
                  <div
                    className="prose prose-invert prose-sm max-w-none"
                    style={{
                      marginTop: 12, color: "var(--ds-fg-muted)",
                      fontSize: 14, lineHeight: 1.7, maxWidth: "65ch",
                    }}
                    dangerouslySetInnerHTML={{ __html: body }}
                  />
                </>
              );
            })()}
          </section>

          {entities && ((entities.requirements?.length ?? 0) > 0 || (entities.skills?.length ?? 0) > 0) && (
            <section className="space-y-5">
              {entities.requirements && entities.requirements.length > 0 && (
                <div>
                  <h3 className="ds-h3">Requirements</h3>
                  <ul style={{ marginTop: 12, color: "var(--ds-fg-muted)", fontSize: 14, lineHeight: 1.7, paddingLeft: 18, maxWidth: "65ch" }}>
                    {entities.requirements.map((r: string, i: number) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                </div>
              )}
              {entities.skills && entities.skills.length > 0 && (
                <div>
                  <h3 className="ds-h3">Skills</h3>
                  <div className="flex flex-wrap" style={{ gap: 6, marginTop: 12 }}>
                    {entities.skills.map((s: string, i: number) => (
                      <span key={i} className="ds-pill ds-mono" style={{ fontSize: 11 }}>{s}</span>
                    ))}
                  </div>
                </div>
              )}
              {entities.nice_to_have && entities.nice_to_have.length > 0 && (
                <div>
                  <h3 className="ds-h3">Nice to have</h3>
                  <div className="flex flex-wrap" style={{ gap: 6, marginTop: 12 }}>
                    {entities.nice_to_have.map((s: string, i: number) => (
                      <span key={i} className="ds-pill ds-mono ds-dim" style={{ fontSize: 11 }}>{s}</span>
                    ))}
                  </div>
                </div>
              )}
            </section>
          )}

        </div>

        {/* ── RIGHT COLUMN — sticky score breakdown ── */}
        <aside className="min-w-0">
          <div className="ds-card" style={{ padding: 18, position: "sticky", top: 80 }}>
            <div className="flex items-baseline justify-between">
              <h3 className="ds-h3">Score breakdown</h3>
              {score?.deep_score?.recommendation && (
                <span className="ds-mono ds-faint" style={{ fontSize: 11 }}>
                  {score.deep_score.recommendation.replace("_", " ")}
                </span>
              )}
            </div>

            <div className="flex flex-col" style={{ gap: 12, marginTop: 14 }}>
              <ScoreAxis label="Overall fit" value={overallFit} />
              {score?.title_score !== undefined && score?.title_score !== null && (
                <ScoreAxis label="Title match" value={pct(score.title_score, 20)} />
              )}
              {score?.skill_score !== undefined && score?.skill_score !== null && (
                <ScoreAxis label="Skills overlap" value={pct(score.skill_score, 25)} />
              )}
              {score?.seniority_score !== undefined && score?.seniority_score !== null && (
                <ScoreAxis label="Seniority" value={pct(score.seniority_score, 15)} />
              )}
              {score?.geo_score !== undefined && score?.geo_score !== null && (
                <ScoreAxis label="Geo fit" value={pct(score.geo_score, 15)} />
              )}
              {score?.remote_score !== undefined && score?.remote_score !== null && (
                <ScoreAxis label="Remote policy" value={pct(score.remote_score, 5)} />
              )}
              {score?.industry_score !== undefined && score?.industry_score !== null && (
                <ScoreAxis label="Industry" value={pct(score.industry_score, 10)} />
              )}
              {/* Salary band + Visa / sponsorship were intentionally removed
                  from the visible breakdown — both axes default to a neutral
                  5/10 on the vast majority of postings (salary unlisted,
                  sponsorship unknown), so the bars were misleading. The
                  backend still computes them and they're still on the
                  JobScore row, just hidden from the sidebar. */}
            </div>

            {/* Details */}
            <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--ds-line)" }}>
              <div className="ds-mono ds-faint" style={{ fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase" }}>
                Details
              </div>
              <div className="flex flex-col" style={{ gap: 8, marginTop: 10, fontSize: 13 }}>
                {job.employment_type && (
                  <div className="flex justify-between">
                    <span className="ds-muted">Type</span>
                    <span style={{ textTransform: "capitalize" }}>{job.employment_type?.replace("_", " ")}</span>
                  </div>
                )}
                {job.seniority && (
                  <div className="flex justify-between">
                    <span className="ds-muted">Seniority</span>
                    <span style={{ textTransform: "capitalize" }}>{job.seniority}</span>
                  </div>
                )}
                {job.country && (
                  <div className="flex justify-between">
                    <span className="ds-muted">Country</span>
                    <span className="ds-mono">{job.country}</span>
                  </div>
                )}
                {entities?.sponsorship_available !== null && entities?.sponsorship_available !== undefined && (
                  <div className="flex justify-between">
                    <span className="ds-muted">Sponsorship</span>
                    <span className={entities.sponsorship_available ? "ds-accent-fg" : ""}>
                      {entities.sponsorship_available ? "Yes" : "No"}
                    </span>
                  </div>
                )}
                {job.discovered_at && (
                  <div className="flex justify-between">
                    <span className="ds-muted">Discovered</span>
                    <span className="ds-mono ds-dim" style={{ fontSize: 12 }}>
                      {new Date(job.discovered_at).toLocaleDateString()}
                    </span>
                  </div>
                )}
                {/* Freshness: closed jobs are expired automatically, but a
                    recent "last listed" date is the clearest sign it's open. */}
                <div className="flex justify-between">
                  <span className="ds-muted">Last listed</span>
                  <span className="ds-mono ds-dim" style={{ fontSize: 12 }}>
                    {job.last_seen_at ? new Date(job.last_seen_at).toLocaleDateString() : "Not yet re-checked"}
                  </span>
                </div>
                {job.last_checked_at && (
                  <div className="flex justify-between">
                    <span className="ds-muted">Link checked</span>
                    <span className="ds-mono ds-dim" style={{ fontSize: 12 }}>
                      {new Date(job.last_checked_at).toLocaleDateString()}
                    </span>
                  </div>
                )}
              </div>
            </div>

            {score?.deep_score && (
              <button
                type="button"
                className="ds-btn ghost"
                style={{ width: "100%", marginTop: 14, fontSize: 12 }}
                onClick={() =>
                  deepScore.mutate(id, {
                    onSuccess: () => toast.success("Fit analysis updated"),
                    onError: (e: any) => toast.error("Analysis failed", { description: e?.message }),
                  })
                }
                disabled={deepScore.isPending}
              >
                {deepScore.isPending && <Loader2 className="h-3 w-3 animate-spin" />}
                Re-analyze
              </button>
            )}
          </div>
        </aside>
      </div>
      </div>
    </div>
  );
}
