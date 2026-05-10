"use client";

import { useState } from "react";
import { Loader2, Sparkles, Wand2, Star, Copy, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTailorBullets, type TailoredBullet } from "@/hooks/use-api";

/**
 * Tailored-bullets viewer for the Review Queue's "Bullets" tab.
 *
 * Re-ranks + rewrites the user's resume bullets for a specific job.
 * Lazy: runs the LLM only when the user lands on the tab (or hits
 * Re-tailor), so the main Generate Application flow stays fast.
 *
 * Reuses everything already in the project:
 *   - CandidateBullet rows populated by the resume parser
 *   - User's writing samples (summary + cover_letter kinds) for voice
 *   - Job entities (skills / requirements / keywords) the scorer extracts
 *
 * Hard rule baked into the prompt: rewrites cover the SAME achievement
 * as the original — never invent a tool, metric, employer, or outcome.
 */
export function TailoredBulletsPanel({ jobId }: { jobId: string }) {
  const tailor = useTailorBullets(jobId);
  const bullets = tailor.data?.bullets ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <p className="text-sm font-medium flex items-center gap-2">
            <Wand2 className="h-3.5 w-3.5 text-amber-400" />
            Bullets re-ranked for this role
          </p>
          <p className="text-xs text-muted-foreground mt-1 max-w-md leading-relaxed">
            Each of your resume bullets, re-ordered by relevance to this JD and
            rewritten in your voice. Never invents facts — only changes
            emphasis. Copy any tailored row into your CV.
          </p>
        </div>
        <Button
          size="sm"
          onClick={() => tailor.mutate()}
          disabled={tailor.isPending}
        >
          {tailor.isPending ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Tailoring…
            </>
          ) : (
            <>
              <Sparkles className="h-3.5 w-3.5" />
              {bullets.length > 0 ? "Re-tailor" : "Tailor bullets"}
            </>
          )}
        </Button>
      </div>

      {tailor.isError && (
        <p className="text-sm text-destructive">
          {tailor.error?.message || "Tailoring failed"}
        </p>
      )}

      {!tailor.data && !tailor.isPending && !tailor.isError && (
        <div className="text-center py-8 space-y-2 rounded-lg border border-white/[0.06] bg-white/[0.01]">
          <Wand2 className="h-7 w-7 mx-auto text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">
            Click <span className="text-foreground font-medium">Tailor bullets</span> to
            run Claude over your bullet bank.
          </p>
          <p className="text-xs text-muted-foreground/70">
            Takes about 10–15 seconds.
          </p>
        </div>
      )}

      {tailor.isPending && !tailor.data && (
        <div className="text-center py-8 space-y-2 rounded-lg border border-white/[0.06] bg-white/[0.01]">
          <Loader2 className="h-6 w-6 animate-spin mx-auto text-amber-400" />
          <p className="text-sm text-muted-foreground">
            Reading your bullets, comparing them to this JD, rewriting for fit…
          </p>
        </div>
      )}

      {bullets.length > 0 && (
        <div className="space-y-3">
          {bullets.map((b) => (
            <BulletRow key={b.id} bullet={b} />
          ))}
        </div>
      )}
    </div>
  );
}

function RelevanceStars({ value }: { value: number }) {
  if (value <= 0) {
    return (
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60">
        unranked
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-0.5"
      aria-label={`${value} of 5 stars`}
    >
      {[1, 2, 3, 4, 5].map((i) => (
        <Star
          key={i}
          className={`h-3 w-3 ${
            i <= value ? "fill-amber-400 text-amber-400" : "text-white/[0.12]"
          }`}
        />
      ))}
    </span>
  );
}

function relevanceLabel(value: number): string {
  if (value >= 5) return "Direct hit";
  if (value === 4) return "Strong match";
  if (value === 3) return "Useful";
  if (value === 2) return "Tangential";
  if (value === 1) return "Stretch";
  return "Unranked";
}

function BulletRow({ bullet }: { bullet: TailoredBullet }) {
  const [copied, setCopied] = useState(false);
  const onCopy = () => {
    navigator.clipboard.writeText(bullet.tailored).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };
  return (
    <div className="rounded-lg border border-white/[0.06] bg-white/[0.01] p-4 space-y-2.5 hover:border-white/[0.1] transition-colors">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <RelevanceStars value={bullet.relevance} />
          <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
            {relevanceLabel(bullet.relevance)}
          </span>
        </div>
        <Button variant="ghost" size="sm" onClick={onCopy}>
          {copied ? (
            <>
              <Check className="h-3.5 w-3.5 text-emerald-400" /> Copied
            </>
          ) : (
            <>
              <Copy className="h-3.5 w-3.5" /> Copy tailored
            </>
          )}
        </Button>
      </div>
      <div className="grid sm:grid-cols-2 gap-3">
        <div>
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground/70 mb-1">
            Original
          </p>
          <p className="text-sm leading-relaxed text-muted-foreground">
            {bullet.original}
          </p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wider text-amber-400/80 mb-1">
            Tailored for this role
          </p>
          <p className="text-sm leading-relaxed text-foreground">
            {bullet.tailored}
          </p>
        </div>
      </div>
      {bullet.why_it_matches && bullet.relevance > 0 && (
        <p className="flex gap-2 text-xs text-muted-foreground italic pt-1 border-t border-white/[0.04]">
          <span className="text-amber-400/70 not-italic">Why:</span>
          <span>{bullet.why_it_matches}</span>
        </p>
      )}
    </div>
  );
}
