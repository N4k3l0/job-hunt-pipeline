"use client";

/**
 * Score component — 3 variants (ring, edge, mono).
 *
 * Color rule (from the design brief): teal for ≥80, neutral grays for
 * the rest. No traffic-light system. A score of 92 is genuinely
 * exceptional and should feel that way visually; 60-79 is "fine but
 * not a top match"; below 60 is unobtrusive.
 *
 * Ported from the Claude Design handoff (score.jsx). The CSS classes
 * live in design-tokens.css.
 */

import { cn } from "@/lib/utils";

export type ScoreVariant = "ring" | "edge" | "mono";

function scoreClass(score: number | null | undefined): string {
  if (score == null) return "ds-s-low";
  if (score >= 80) return "ds-s-top";
  if (score >= 60) return "ds-s-mid";
  return "ds-s-low";
}

interface ScoreRingProps {
  score: number | null;
  size?: number;
  stroke?: number;
}

export function ScoreRing({ score, size = 44, stroke = 2 }: ScoreRingProps) {
  if (score == null) {
    return (
      <div className="ds-score-ring" style={{ width: size, height: size }} title="No score">
        <svg width={size} height={size}>
          <circle
            cx={size / 2}
            cy={size / 2}
            r={(size - stroke) / 2 - 1}
            fill="none"
            stroke="var(--ds-line)"
            strokeWidth={stroke}
          />
        </svg>
        <div className="ds-score-num ds-faint">—</div>
      </div>
    );
  }
  const r = (size - stroke) / 2 - 1;
  const C = 2 * Math.PI * r;
  const offset = C * (1 - score / 100);
  const top = score >= 80;
  return (
    <div className="ds-score-ring" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--ds-line)"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={top ? "var(--ds-accent)" : "var(--ds-fg-muted)"}
          strokeWidth={stroke}
          strokeDasharray={C}
          strokeDashoffset={offset}
          strokeLinecap="round"
          opacity={top ? 1 : 0.7}
        />
      </svg>
      <div className={cn("ds-score-num", scoreClass(score))}>{Math.round(score)}</div>
    </div>
  );
}

export function ScoreEdge({ score }: { score: number | null }) {
  const top = score != null && score >= 80;
  return (
    <div className="ds-score-edge">
      <div
        className="ds-bar"
        style={{
          background: top
            ? "linear-gradient(to bottom, var(--ds-accent) 0%, var(--ds-accent) 60%, var(--ds-line) 60%, var(--ds-line) 100%)"
            : score == null
              ? "var(--ds-line)"
              : `linear-gradient(to bottom, var(--ds-fg-muted) 0%, var(--ds-fg-muted) ${100 - score}%, var(--ds-line) ${100 - score}%, var(--ds-line) 100%)`,
        }}
      />
      <div className={cn("ds-num", scoreClass(score))}>
        {score == null ? <span className="ds-faint">—</span> : Math.round(score)}
      </div>
    </div>
  );
}

export function ScoreMono({ score }: { score: number | null }) {
  return (
    <div className="ds-score-mono">
      <span className={cn("ds-n ds-mono", scoreClass(score))}>
        {score == null ? "—" : Math.round(score)}
      </span>
      <span className="ds-of">/100</span>
    </div>
  );
}

export function Score({ score, variant }: { score: number | null; variant: ScoreVariant }) {
  if (variant === "edge") return <ScoreEdge score={score} />;
  if (variant === "mono") return <ScoreMono score={score} />;
  return <ScoreRing score={score} />;
}

/**
 * ScoreAxis — labeled horizontal bar for the score-breakdown sidebar
 * on Job Detail. Teal fill at ≥80, neutral gray below. Width animates
 * from 0 on mount so the breakdown feels alive without using springs.
 */
export function ScoreAxis({
  label,
  value,
  max = 100,
}: { label: string; value: number; max?: number }) {
  const clamped = Math.max(0, Math.min(max, value));
  const pct = (clamped / max) * 100;
  const top = clamped >= 80;
  return (
    <div className="flex flex-col" style={{ gap: 4 }}>
      <div className="flex items-baseline justify-between">
        <span style={{ fontSize: 12, color: "var(--ds-fg-muted)", fontWeight: 500 }}>{label}</span>
        <span className={`ds-mono ${top ? "ds-s-top" : ""}`} style={{ fontSize: 13, fontWeight: 600, letterSpacing: "-0.01em" }}>
          {Math.round(clamped)}<span style={{ color: "var(--ds-fg-faint)", fontWeight: 400 }}>/{max}</span>
        </span>
      </div>
      <div style={{ height: 3, background: "var(--ds-line)", borderRadius: 2, overflow: "hidden" }}>
        <div style={{
          width: `${pct}%`,
          height: "100%",
          background: top ? "var(--ds-accent)" : "var(--ds-fg-muted)",
          borderRadius: 2,
          transition: "width 360ms cubic-bezier(0.32,0.72,0.32,1)",
        }} />
      </div>
    </div>
  );
}

/** Hero score — used in the editorial top-match card. Larger + more
 * dramatic than the inline variants. */
export function ScoreHero({ score, variant }: { score: number; variant: ScoreVariant }) {
  if (variant === "mono") {
    return (
      <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
        <span
          className="ds-mono ds-s-top"
          style={{
            fontSize: 64,
            fontWeight: 600,
            letterSpacing: "-0.05em",
            lineHeight: 1,
          }}
        >
          {Math.round(score)}
        </span>
        <span className="ds-mono ds-faint" style={{ fontSize: 14 }}>/100</span>
      </div>
    );
  }
  if (variant === "edge") {
    return (
      <div style={{ display: "flex", alignItems: "stretch", gap: 14, height: 64 }}>
        <div
          style={{
            width: 4,
            borderRadius: 2,
            background: "linear-gradient(to bottom, var(--ds-accent), var(--ds-accent-edge))",
          }}
        />
        <div style={{ display: "flex", flexDirection: "column", justifyContent: "center" }}>
          <span
            className="ds-mono ds-s-top"
            style={{
              fontSize: 38,
              fontWeight: 600,
              letterSpacing: "-0.04em",
              lineHeight: 1,
            }}
          >
            {Math.round(score)}
          </span>
          <span
            className="ds-mono ds-faint"
            style={{ fontSize: 11, marginTop: 4, letterSpacing: "0.04em" }}
          >
            OVERALL FIT
          </span>
        </div>
      </div>
    );
  }
  // Ring — larger
  return <ScoreRing score={score} size={72} stroke={3} />;
}
