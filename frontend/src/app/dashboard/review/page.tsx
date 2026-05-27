"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import {
  CheckCircle2, XCircle, Download,
  AlertCircle, Loader2, ExternalLink, Copy, Check, Send,
  RefreshCw, Sparkles, Search, Linkedin, AtSign, Quote,
} from "lucide-react";
import { TailoredBulletsPanel } from "@/components/tailored-bullets-panel";
import { OperationProgress } from "@/components/operation-progress";
import {
  useReviewQueue, useApproveTailored, useUpdateStatus, useGenerateTailored,
  useUpdateTailored, useRegenerateSection,
  useJobContact, useFindJobContact,
} from "@/hooks/use-api";
import type { RegeneratableSection } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api-client";
import { useQueryClient } from "@tanstack/react-query";

function formatFollowUp(date: Date) {
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function ElapsedTime({ since }: { since: string }) {
  // Live-ticking elapsed time so the user can see the worker is making progress
  // even when the step label hasn't changed yet.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const seconds = Math.max(0, Math.floor((now - new Date(since).getTime()) / 1000));
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return (
    <span className="font-mono text-xs text-muted-foreground tabular-nums">
      {m > 0 ? `${m}m ${s.toString().padStart(2, "0")}s` : `${s}s`}
    </span>
  );
}

const TAILORING_STEPS = [
  "Queued",
  "Fetching job description",
  "Tailoring resume",
  "Writing cover letter",
  "Drafting outreach",
  "Answering screening questions",
  "Generating PDF",
];

type EditableField = "tailored_summary" | "cover_letter" | "recruiter_message";

function confidenceTone(c: string | null | undefined) {
  // All three states use accent in v2 — we just adjust intensity. Avoids
  // the green/amber/grey traffic-light that the design system bans.
  if (c === "high") return "text-[var(--ds-accent)] border-[var(--ds-accent-edge)] bg-[var(--ds-accent-soft)]";
  if (c === "medium") return "text-[var(--ds-fg)] border-[var(--ds-line-strong)] bg-[var(--ds-bg-elev-2)]";
  return "text-[var(--ds-fg-muted)] border-[var(--ds-line)]";
}

function ContactPanel({
  jobId,
  outreachMessage,
}: {
  jobId: string;
  outreachMessage?: string | null;
}) {
  const { data, isLoading } = useJobContact(jobId);
  const find = useFindJobContact(jobId);
  const contact = find.data?.contact ?? data?.contact ?? null;
  const noContactYet = !isLoading && !contact;
  const toast = useToast();
  const [linkedInSent, setLinkedInSent] = useState(false);

  // One-click bridge from "we generated an outreach draft" to "the
  // user is in LinkedIn ready to paste it." LinkedIn doesn't reliably
  // accept a pre-filled body in their compose-with-message URL (they
  // strip it for spam protection), so the safe path is: open the
  // contact's profile + drop the message in the clipboard. User
  // clicks Message on the profile, paste, send.
  const handleSendViaLinkedIn = async () => {
    if (!contact?.linkedin_url) return;
    const message = (outreachMessage || "").trim();
    if (message) {
      try {
        await navigator.clipboard.writeText(message);
      } catch {
        toast.error("Couldn't copy message", {
          description: "Open the LinkedIn tab and copy from the Outreach box manually.",
        });
        return;
      }
    }
    window.open(contact.linkedin_url, "_blank", "noopener,noreferrer");
    setLinkedInSent(true);
    setTimeout(() => setLinkedInSent(false), 2500);
    toast.success(
      message ? "Message copied — paste it on their profile" : "Opened on LinkedIn",
      message
        ? { description: "Click the Message button at the top of their LinkedIn profile, then paste." }
        : undefined,
    );
  };

  return (
    <div
      style={{
        background: "var(--ds-bg-elev-2)",
        border: "1px solid var(--ds-line)",
        borderRadius: 8,
        padding: 16,
        marginBottom: 16,
      }}
    >
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <p className="text-xs uppercase tracking-wider text-muted-foreground mb-1">
            Decision maker
          </p>
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : contact ? (
            <div className="space-y-1">
              <p className="text-sm font-semibold">
                {contact.name || "Unknown"}
                {contact.title && (
                  <span className="ml-2 font-normal text-muted-foreground">
                    {contact.title}
                  </span>
                )}
              </p>
              {contact.confidence && (
                <Badge
                  variant="outline"
                  className={`text-xs ${confidenceTone(contact.confidence)}`}
                >
                  {contact.confidence} confidence
                </Badge>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              Not searched yet. Click below to find the hiring manager.
            </p>
          )}
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => find.mutate({ force: !!contact })}
          disabled={find.isPending}
        >
          {find.isPending ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Searching…
            </>
          ) : contact ? (
            <>
              <RefreshCw className="h-3.5 w-3.5" />
              Re-search
            </>
          ) : (
            <>
              <Search className="h-3.5 w-3.5" />
              Find decision maker
            </>
          )}
        </Button>
      </div>

      {find.isError && (
        <p className="mt-3 text-sm text-destructive">
          Lookup failed. Try again in a moment.
        </p>
      )}

      {contact && (
        <div className="mt-3 space-y-2 text-sm">
          {contact.linkedin_url && (
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <a
                href={contact.linkedin_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 min-w-0"
                style={{ color: "var(--ds-accent)" }}
              >
                <Linkedin className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">{contact.linkedin_url.replace(/^https?:\/\//, "")}</span>
                <ExternalLink className="h-3 w-3 opacity-60 shrink-0" />
              </a>
              <Button
                size="sm"
                onClick={handleSendViaLinkedIn}
                disabled={!contact.linkedin_url}
                title={
                  outreachMessage
                    ? "Copies the outreach message to clipboard and opens their LinkedIn profile in a new tab."
                    : "Opens their LinkedIn profile in a new tab. Write or generate an outreach message first to also copy it to clipboard."
                }
                className="bg-[#0a66c2] hover:bg-[#0858a8] text-white"
              >
                {linkedInSent ? (
                  <>
                    <Check className="h-3.5 w-3.5" />
                    Opened
                  </>
                ) : (
                  <>
                    <Linkedin className="h-3.5 w-3.5" />
                    Send via LinkedIn
                  </>
                )}
              </Button>
            </div>
          )}
          {contact.email_guess && (
            <div className="flex items-center gap-2 text-muted-foreground">
              <AtSign className="h-3.5 w-3.5" />
              <code className="text-xs">{contact.email_guess}</code>
              <span className="text-xs italic">(best-guess pattern)</span>
            </div>
          )}
          {contact.source_notes && (
            <p className="flex gap-2 text-xs text-muted-foreground italic">
              <Quote className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              {contact.source_notes}
            </p>
          )}
          {contact.citations && contact.citations.length > 0 && (
            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer hover:text-foreground">
                Sources ({contact.citations.length})
              </summary>
              <ul className="mt-1 space-y-0.5 pl-4">
                {contact.citations.map((c, i) => (
                  <li key={i}>
                    <a
                      href={c.url}
                      target="_blank"
                      rel="noreferrer"
                      className="hover:text-foreground"
                    >
                      {c.title || c.url}
                    </a>
                  </li>
                ))}
              </ul>
            </details>
          )}
          {contact.searched_at && (
            <p className="text-xs text-muted-foreground/70">
              Last searched {new Date(contact.searched_at).toLocaleDateString()}
            </p>
          )}
        </div>
      )}

      <div className="mt-3">
        <OperationProgress
          active={find.isPending}
          stages={[
            { label: "Searching company leadership pages", durationMs: 3500, tip: "Looking at the company's About / Team / careers pages." },
            { label: "Cross-referencing LinkedIn", durationMs: 6000, tip: "Finding the hiring manager or department head for this role." },
            { label: "Verifying the match", durationMs: 4000, tip: "Confirming role, citing sources, scoring confidence." },
            { label: "Best-guess email pattern", durationMs: 2500, tip: "Building first.last@company patterns where we can." },
          ]}
        />
      </div>
    </div>
  );
}

type TabKey = "summary" | "bullets" | "cover" | "outreach";

function EditableMaterials({
  review,
  draft,
  onChange,
  onAutoSave,
  onCopy,
  copied,
  onApprove,
  approved,
  approving,
  onRegenerate,
}: {
  review: any;
  draft?: { tailored_summary?: string; cover_letter?: string; recruiter_message?: string };
  onChange: (field: EditableField, value: string) => void;
  onAutoSave: () => void;
  onCopy: (text: string, label: string) => void;
  copied: string | null;
  onApprove: () => void;
  approved: boolean;
  approving: boolean;
  onRegenerate: (section: RegeneratableSection, guidance?: string) => Promise<void>;
}) {
  const [tab, setTab] = useState<TabKey>("summary");
  const v = (field: EditableField, fallback: string | null) =>
    draft?.[field] ?? fallback ?? "";

  const attribution = (() => {
    const model = review.model_used || "claude-sonnet";
    const tokens = review.tokens_used;
    const seconds = review.generation_time_seconds;
    const parts = [`Generated by ${model}`];
    if (seconds) parts.push(`${Math.round(seconds)}s`);
    if (tokens) parts.push(`${tokens.toLocaleString()} tokens`);
    return parts.join(" · ");
  })();

  const tabs: { key: TabKey; label: string; count?: number }[] = [
    { key: "summary", label: "Summary" },
    { key: "bullets", label: "Bullets" },
    { key: "cover", label: "Cover letter" },
    { key: "outreach", label: "Outreach" },
  ];

  return (
    <div>
      {/* Tab strip — design pattern: thin underline rail, active gets a 1px
          accent underline. No icons, no full-width flex-1 stretch. */}
      <div className="rev-tabs" role="tablist">
        {tabs.map((t) => (
          <button
            key={t.key}
            role="tab"
            type="button"
            aria-selected={tab === t.key}
            data-active={tab === t.key}
            onClick={() => setTab(t.key)}
            className="rev-tab"
          >
            {t.label}
            {t.count != null && (
              <span
                className="ds-mono"
                style={{ marginLeft: 6, color: "var(--ds-fg-faint)", fontSize: 12 }}
              >
                · {t.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {tab === "summary" && (
        <TabBody
          label="Tailored summary"
          hint="First-person paragraph that opens your resume."
          value={v("tailored_summary", review.tailored_summary)}
          placeholder="No tailored summary generated yet."
          field="tailored_summary"
          section="tailored_summary"
          onChange={onChange}
          onAutoSave={onAutoSave}
          onCopy={onCopy}
          copied={copied}
          onApprove={onApprove}
          approved={approved}
          approving={approving}
          onRegenerate={onRegenerate}
          attribution={attribution}
        />
      )}

      {tab === "bullets" && (
        <BulletsTab
          jobId={review.job_id}
          approved={approved}
          approving={approving}
          onApprove={onApprove}
          attribution={attribution}
        />
      )}

      {tab === "cover" && (
        <TabBody
          label="Cover letter"
          hint="Four short paragraphs, tone-matched to the company's voice."
          value={v("cover_letter", review.cover_letter)}
          placeholder="No cover letter generated yet."
          field="cover_letter"
          section="cover_letter"
          onChange={onChange}
          onAutoSave={onAutoSave}
          onCopy={onCopy}
          copied={copied}
          onApprove={onApprove}
          approved={approved}
          approving={approving}
          onRegenerate={onRegenerate}
          attribution={attribution}
        />
      )}

      {tab === "outreach" && (
        <>
          {review.job_id && (
            <div style={{ marginTop: 18 }}>
              <ContactPanel
                jobId={review.job_id}
                outreachMessage={v("recruiter_message", review.recruiter_message)}
              />
            </div>
          )}
          <TabBody
            label="Outreach DM"
            hint="Shorter — for LinkedIn or a warm intro reply."
            value={v("recruiter_message", review.recruiter_message)}
            placeholder="No outreach message generated yet."
            field="recruiter_message"
            section="recruiter_message"
            onChange={onChange}
            onAutoSave={onAutoSave}
            onCopy={onCopy}
            copied={copied}
            onApprove={onApprove}
            approved={approved}
            approving={approving}
            onRegenerate={onRegenerate}
            attribution={attribution}
          />
        </>
      )}
    </div>
  );
}

function TabBody({
  label,
  hint,
  value,
  placeholder,
  field,
  section,
  onChange,
  onAutoSave,
  onCopy,
  copied,
  onApprove,
  approved,
  approving,
  onRegenerate,
  attribution,
}: {
  label: string;
  hint: string;
  value: string;
  placeholder: string;
  field: EditableField;
  section: RegeneratableSection;
  onChange: (field: EditableField, value: string) => void;
  onAutoSave: () => void;
  onCopy: (text: string, label: string) => void;
  copied: string | null;
  onApprove: () => void;
  approved: boolean;
  approving: boolean;
  onRegenerate: (section: RegeneratableSection, guidance?: string) => Promise<void>;
  attribution: string;
}) {
  // First word of the label, lowercased, drives the per-tab button copy.
  // "Tailored summary" -> "summary", "Cover letter" -> "cover", etc.
  const shortLabel = label.split(" ").slice(-1)[0].toLowerCase();
  const copyKey = `tab-${field}`;
  return (
    <div className="rev-tabbody" style={{ marginTop: 18 }}>
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div style={{ minWidth: 0 }}>
          <h2 className="ds-h2" style={{ fontSize: 17, lineHeight: 1.3 }}>{label}</h2>
          <p style={{ fontSize: 13, color: "var(--ds-fg-muted)", marginTop: 4 }}>{hint}</p>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <RegenerateControl section={section} onSubmit={onRegenerate} />
          <Button
            variant="outline"
            size="sm"
            onClick={() => onCopy(value, copyKey)}
            disabled={!value}
          >
            {copied === copyKey ? (
              <Check className="h-3.5 w-3.5" style={{ color: "var(--ds-accent)" }} />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
            {copied === copyKey ? "Copied" : "Copy"}
          </Button>
        </div>
      </div>

      <div
        style={{
          marginTop: 16,
          padding: 22,
          background: "var(--ds-bg-elev-1)",
          border: "1px solid var(--ds-line)",
          borderRadius: 8,
        }}
      >
        <textarea
          value={value}
          onChange={(e) => onChange(field, e.target.value)}
          onBlur={onAutoSave}
          placeholder={placeholder}
          spellCheck
          style={{
            display: "block",
            width: "100%",
            maxWidth: "65ch",
            minHeight: 280,
            resize: "vertical",
            background: "transparent",
            color: "var(--ds-fg)",
            border: 0,
            outline: 0,
            fontSize: 15,
            lineHeight: 1.7,
            fontFamily: "var(--ds-font-sans)",
            whiteSpace: "pre-line",
            padding: 0,
          }}
        />
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginTop: 14,
          flexWrap: "wrap",
        }}
      >
        <Button onClick={onApprove} disabled={approved || approving}>
          {approving ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Check className="h-3.5 w-3.5" />
          )}
          {approved ? "Approved" : `Approve ${shortLabel}`}
        </Button>
        <span style={{ flex: 1 }} />
        <span
          className="ds-mono"
          style={{ color: "var(--ds-fg-dim)", fontSize: 11 }}
        >
          {attribution}
        </span>
      </div>
    </div>
  );
}

function BulletsTab({
  jobId,
  approved,
  approving,
  onApprove,
  attribution,
}: {
  jobId: string | null;
  approved: boolean;
  approving: boolean;
  onApprove: () => void;
  attribution: string;
}) {
  return (
    <div className="rev-tabbody" style={{ marginTop: 18 }}>
      <div>
        <h2 className="ds-h2" style={{ fontSize: 17, lineHeight: 1.3 }}>Tailored resume bullets</h2>
        <p style={{ fontSize: 13, color: "var(--ds-fg-muted)", marginTop: 4 }}>
          Each bullet from your resume bank, re-ranked + rewritten for this role. Goes into the
          Experience section of your CV — pick the top 3–6 by relevance and copy.
        </p>
      </div>
      <div
        style={{
          marginTop: 16,
          padding: 22,
          background: "var(--ds-bg-elev-1)",
          border: "1px solid var(--ds-line)",
          borderRadius: 8,
        }}
      >
        {jobId ? <TailoredBulletsPanel jobId={jobId} /> : null}
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginTop: 14,
          flexWrap: "wrap",
        }}
      >
        <Button onClick={onApprove} disabled={approved || approving}>
          {approving ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Check className="h-3.5 w-3.5" />
          )}
          {approved ? "Approved" : "Approve bullets"}
        </Button>
        <span style={{ flex: 1 }} />
        <span
          className="ds-mono"
          style={{ color: "var(--ds-fg-dim)", fontSize: 11 }}
        >
          {attribution}
        </span>
      </div>
    </div>
  );
}

function AnalysisChips({ review }: { review: any }) {
  const [open, setOpen] = useState(false);
  const matched = review.keyword_matches?.matched ?? [];
  const unmatched = review.keyword_matches?.unmatched ?? [];
  const strengths = review.validation_notes?.strongest_matches ?? [];
  const gaps = review.validation_notes?.gaps ?? [];
  if (matched.length + unmatched.length + strengths.length + gaps.length === 0) {
    return null;
  }
  return (
    <div style={{ marginTop: 6 }}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 10,
          padding: "6px 10px",
          background: "var(--ds-bg-elev-1)",
          border: "1px solid var(--ds-line)",
          borderRadius: 6,
          color: "var(--ds-fg-muted)",
          fontSize: 12,
          cursor: "pointer",
          transition: "background 120ms ease",
        }}
      >
        <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <CheckCircle2 className="h-3 w-3" style={{ color: "var(--ds-accent)" }} />
          <span className="ds-mono" style={{ color: "var(--ds-fg)" }}>
            {matched.length}
          </span>
          <span>matched</span>
        </span>
        {unmatched.length > 0 && (
          <>
            <span style={{ color: "var(--ds-fg-faint)" }}>·</span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
              <AlertCircle className="h-3 w-3" style={{ color: "var(--ds-fg-dim)" }} />
              <span className="ds-mono" style={{ color: "var(--ds-fg)" }}>
                {unmatched.length}
              </span>
              <span>gaps</span>
            </span>
          </>
        )}
        <span style={{ color: "var(--ds-fg-faint)", marginLeft: 4 }}>
          {open ? "Hide" : "Show"}
        </span>
      </button>
      {open && (
        <div
          style={{
            marginTop: 10,
            padding: 14,
            background: "var(--ds-bg-elev-1)",
            border: "1px solid var(--ds-line)",
            borderRadius: 8,
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: 16,
          }}
        >
          {matched.length > 0 && (
            <div>
              <div className="ds-mono" style={{ fontSize: 10, letterSpacing: "0.1em", color: "var(--ds-fg-faint)", textTransform: "uppercase", marginBottom: 6 }}>
                Matched keywords
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {matched.map((kw: string) => (
                  <span
                    key={kw}
                    style={{
                      fontSize: 11,
                      padding: "2px 8px",
                      borderRadius: 4,
                      background: "var(--ds-accent-soft)",
                      border: "1px solid var(--ds-accent-edge)",
                      color: "var(--ds-accent)",
                    }}
                  >
                    {kw}
                  </span>
                ))}
              </div>
            </div>
          )}
          {unmatched.length > 0 && (
            <div>
              <div className="ds-mono" style={{ fontSize: 10, letterSpacing: "0.1em", color: "var(--ds-fg-faint)", textTransform: "uppercase", marginBottom: 6 }}>
                Gaps
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {unmatched.map((kw: string) => (
                  <span
                    key={kw}
                    style={{
                      fontSize: 11,
                      padding: "2px 8px",
                      borderRadius: 4,
                      background: "var(--ds-bg-elev-2)",
                      border: "1px dashed var(--ds-line-strong)",
                      color: "var(--ds-fg-muted)",
                      textDecoration: "line-through",
                      textDecorationColor: "var(--ds-fg-dim)",
                    }}
                  >
                    {kw}
                  </span>
                ))}
              </div>
            </div>
          )}
          {strengths.length > 0 && (
            <div>
              <div className="ds-mono" style={{ fontSize: 10, letterSpacing: "0.1em", color: "var(--ds-fg-faint)", textTransform: "uppercase", marginBottom: 6 }}>
                Strengths
              </div>
              <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 4 }}>
                {strengths.map((s: string) => (
                  <li key={s} style={{ fontSize: 12, color: "var(--ds-fg-muted)", lineHeight: 1.45 }}>
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {gaps.length > 0 && (
            <div>
              <div className="ds-mono" style={{ fontSize: 10, letterSpacing: "0.1em", color: "var(--ds-fg-faint)", textTransform: "uppercase", marginBottom: 6 }}>
                Watch-outs
              </div>
              <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 4 }}>
                {gaps.map((g: string) => (
                  <li key={g} style={{ fontSize: 12, color: "var(--ds-fg-muted)", lineHeight: 1.45 }}>
                    {g}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function RegenerateControl({
  section,
  onSubmit,
}: {
  section: RegeneratableSection;
  onSubmit: (section: RegeneratableSection, guidance?: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [guidance, setGuidance] = useState("");
  const [busy, setBusy] = useState(false);

  const placeholder =
    section === "tailored_summary"
      ? "Optional: 'lean harder on AI experience'"
      : section === "cover_letter"
        ? "Optional: 'shorter, less formal'"
        : "Optional: 'more direct, mention the strategy work'";

  const fire = async (withGuidance: boolean) => {
    setBusy(true);
    try {
      await onSubmit(section, withGuidance ? guidance.trim() || undefined : undefined);
      setOpen(false);
      setGuidance("");
    } catch {
      // toast surfaced upstream
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setOpen(true)}
        style={{ color: "var(--ds-fg-muted)" }}
      >
        <Sparkles className="h-3.5 w-3.5" />
        Regenerate with notes…
      </Button>
    );
  }

  return (
    <div
      className="flex items-center gap-1.5"
      style={{
        border: "1px solid var(--ds-accent-edge)",
        background: "var(--ds-accent-soft)",
        borderRadius: 6,
        paddingLeft: 8,
        paddingRight: 4,
        paddingTop: 4,
        paddingBottom: 4,
      }}
    >
      <input
        autoFocus
        type="text"
        value={guidance}
        onChange={(e) => setGuidance(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") fire(true);
          if (e.key === "Escape") {
            setOpen(false);
            setGuidance("");
          }
        }}
        placeholder={placeholder}
        disabled={busy}
        style={{
          background: "transparent",
          fontSize: 13,
          color: "var(--ds-fg)",
          border: 0,
          outline: 0,
          width: 256,
        }}
      />
      <Button
        variant="ghost"
        size="xs"
        onClick={() => {
          setOpen(false);
          setGuidance("");
        }}
        disabled={busy}
        style={{ color: "var(--ds-fg-muted)" }}
      >
        Cancel
      </Button>
      <Button size="xs" onClick={() => fire(true)} disabled={busy}>
        {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
        Regenerate
      </Button>
    </div>
  );
}

function ProgressTimeline({ currentStep }: { currentStep: string | null }) {
  const idx = currentStep ? TAILORING_STEPS.indexOf(currentStep) : -1;
  return (
    <ul style={{ display: "flex", flexDirection: "column", gap: 8, margin: 0, padding: 0, listStyle: "none" }}>
      {TAILORING_STEPS.map((step, i) => {
        const done = idx > i;
        const active = idx === i;
        const optional = step === "Answering screening questions";
        const dotStyle: React.CSSProperties = {
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: active
            ? "var(--ds-accent)"
            : done
              ? "var(--ds-accent)"
              : "var(--ds-line)",
          boxShadow: active ? "0 0 8px var(--ds-accent)" : "none",
          flexShrink: 0,
        };
        const labelColor = active
          ? "var(--ds-fg)"
          : done
            ? "var(--ds-fg-muted)"
            : optional
              ? "var(--ds-fg-faint)"
              : "var(--ds-fg-dim)";
        return (
          <li key={step} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 14 }}>
            <span style={dotStyle} />
            <span
              style={{
                color: labelColor,
                fontWeight: active ? 500 : 400,
                textDecoration: done ? "line-through" : "none",
                textDecorationColor: done ? "var(--ds-accent-edge)" : undefined,
              }}
            >
              {step}
            </span>
            {active && (
              <Loader2
                className="h-3 w-3 animate-spin"
                style={{ color: "var(--ds-accent)" }}
              />
            )}
          </li>
        );
      })}
    </ul>
  );
}

export default function ReviewQueuePage() {
  const { data: queue, isLoading } = useReviewQueue();
  const approve = useApproveTailored();
  const updateStatus = useUpdateStatus();
  const generate = useGenerateTailored();
  const updateTailored = useUpdateTailored();
  const regenerate = useRegenerateSection();
  const toast = useToast();
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  /**
   * Unsaved edits, keyed by tailored-application id. Each entry is a partial
   * patch of the editable fields. Switching between items preserves drafts.
   */
  type Draft = { tailored_summary?: string; cover_letter?: string; recruiter_message?: string };
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});

  const updateDraft = (id: string, field: keyof Draft, value: string) => {
    setDrafts((d) => ({ ...d, [id]: { ...d[id], [field]: value } }));
  };

  const clearDraft = (id: string) => {
    setDrafts((d) => {
      if (!(id in d)) return d;
      const next = { ...d };
      delete next[id];
      return next;
    });
  };

  const copyText = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    setCopied(label);
    toast.success(`${label[0].toUpperCase()}${label.slice(1)} copied`);
    setTimeout(() => setCopied(null), 2000);
  };

  const items = queue ?? [];
  const selected = selectedId ? items.find((i: any) => i.id === selectedId) : items[0];

  /**
   * Opens the company's posting via the resolver chain (handles WWR-style
   * paywalls + Claude fallback). Does NOT mark the job as applied — that
   * was the old "Open & Apply" behavior, but the dashboard's 'Applied'
   * stat then ticked up before the user had actually submitted anything.
   * Users now confirm separately via 'I applied' once the form is in.
   */
  const handleOpenPosting = async (review: any) => {
    if (!(await persistDraftIfDirty(review.id))) return;
    const jobId = review.job_id;
    if (!jobId) {
      toast.error("Couldn't open posting", { description: "Missing job_id on review row." });
      return;
    }
    // Open a placeholder popup synchronously so the popup blocker is happy,
    // then navigate it once the resolver finishes.
    const popup = window.open("about:blank", "_blank");
    if (popup) {
      popup.document.write(
        '<title>Opening posting…</title>' +
        '<style>body{margin:0;display:flex;align-items:center;justify-content:center;' +
        'height:100vh;font-family:system-ui;background:#0a0a0a;color:#a3a3a3}</style>' +
        '<div>Resolving direct apply link…</div>'
      );
    }
    try {
      const data = await api.post<{ url: string; is_direct_ats: boolean }>(
        `/api/v1/jobs/${jobId}/apply`,
      );
      if (popup && !popup.closed) {
        try { popup.opener = null; } catch {}
        popup.location.replace(data.url);
      } else {
        window.open(data.url, "_blank") || (window.location.href = data.url);
      }
    } catch (e: any) {
      if (popup && !popup.closed) popup.close();
      toast.error("Couldn't open posting", { description: e?.message });
    }
  };

  /**
   * Explicit user action: 'I just submitted this application.' Approves
   * the tailored pack (creates the tracking row) and flips status to
   * applied with a 7-day follow-up. Kept separate from handleOpenPosting
   * so opening the page never side-effects the user's stats.
   */
  const handleMarkApplied = async (review: any) => {
    if (!(await persistDraftIfDirty(review.id))) return;
    const followUp = new Date();
    followUp.setDate(followUp.getDate() + 7);
    const followUpIso = followUp.toISOString().slice(0, 10);

    toast.action({
      message: "Marked as Applied",
      description: `Follow-up scheduled for ${formatFollowUp(followUp)}`,
      actionLabel: "Undo",
      duration: 5000,
      onCommit: async () => {
        try {
          const res = await approve.mutateAsync(review.id);
          await updateStatus.mutateAsync({
            id: res.tracking_id,
            status: "applied",
            followUpDate: followUpIso,
          });
          if (selectedId === review.id) setSelectedId(null);
        } catch (err: any) {
          toast.error("Couldn't save status", { description: err?.message });
        }
      },
    });
  };

  const handleClearFailed = () => {
    const failed = (queue ?? []).filter((i: any) => i.approval_status === "failed");
    if (failed.length === 0) return;
    const previous = qc.getQueryData<any[]>(["tailoring", "queue"]);
    qc.setQueryData<any[]>(["tailoring", "queue"], (cur) =>
      (cur ?? []).filter((x: any) => x.approval_status !== "failed"),
    );
    if (selectedId && failed.some((f: any) => f.id === selectedId)) setSelectedId(null);

    toast.action({
      message: `Cleared ${failed.length} failed`,
      actionLabel: "Undo",
      duration: 5000,
      onCommit: async () => {
        try {
          // Run deletes in parallel — failed tailored rows are independent.
          await Promise.all(
            failed.map((f: any) => api.delete(`/api/v1/tailoring/${f.id}`)),
          );
        } catch (err: any) {
          if (previous) qc.setQueryData(["tailoring", "queue"], previous);
          toast.error("Couldn't clear all", { description: err?.message });
        } finally {
          qc.invalidateQueries({ queryKey: ["tailoring"] });
        }
      },
      onUndo: () => {
        if (previous) qc.setQueryData(["tailoring", "queue"], previous);
      },
    });
  };

  const handleSaveDraft = async (review: any) => {
    const draft = drafts[review.id];
    if (!draft) return;
    try {
      await updateTailored.mutateAsync({ id: review.id, data: draft });
      clearDraft(review.id);
      toast.success("Edits saved");
    } catch (err: any) {
      toast.error("Save failed", { description: err?.message });
    }
  };

  // Approval locks the row, so any unsaved edits must be persisted first.
  const persistDraftIfDirty = async (id: string) => {
    const draft = drafts[id];
    if (!draft) return true;
    try {
      await updateTailored.mutateAsync({ id, data: draft });
      clearDraft(id);
      return true;
    } catch (err: any) {
      toast.error("Couldn't save edits", { description: err?.message });
      return false;
    }
  };

  const handleRetry = async (review: any) => {
    try {
      await api.delete(`/api/v1/tailoring/${review.id}`);
      qc.setQueryData<any[]>(["tailoring", "queue"], (cur) =>
        (cur ?? []).filter((x) => x.id !== review.id),
      );
      generate.mutate(review.job_id, {
        onSuccess: () => {
          toast.success("Retrying tailoring");
          setSelectedId(null);
        },
        onError: (err: any) => toast.error("Retry failed", { description: err?.message }),
      });
    } catch (err: any) {
      toast.error("Couldn't retry", { description: err?.message });
    }
  };

  const handleApprove = async (review: any) => {
    if (!(await persistDraftIfDirty(review.id))) return;
    approve.mutate(review.id, {
      onSuccess: () => {
        toast.success("Approved", { description: "Tracked under Applications → Approved" });
        if (selectedId === review.id) setSelectedId(null);
      },
      onError: (err: any) => toast.error("Approve failed", { description: err?.message }),
    });
  };

  /**
   * Delayed delete with undo. Optimistically remove from the cached queue so the
   * list collapses immediately, then either commit the DELETE or restore the
   * cache if the user clicks Undo.
   */
  const handleDelete = (review: any) => {
    const previous = qc.getQueryData<any[]>(["tailoring", "queue"]);
    qc.setQueryData<any[]>(["tailoring", "queue"], (cur) =>
      (cur ?? []).filter((x) => x.id !== review.id),
    );
    if (selectedId === review.id) setSelectedId(null);

    toast.action({
      message: "Discarded application",
      description: review.job?.title ? `${review.job.company} — ${review.job.title}` : undefined,
      actionLabel: "Undo",
      duration: 5000,
      onCommit: async () => {
        try {
          await api.delete(`/api/v1/tailoring/${review.id}`);
        } catch (err: any) {
          // Restore on failure so the user doesn't lose work silently.
          if (previous) qc.setQueryData(["tailoring", "queue"], previous);
          toast.error("Couldn't discard", { description: err?.message });
        } finally {
          qc.invalidateQueries({ queryKey: ["tailoring"] });
        }
      },
      onUndo: () => {
        if (previous) qc.setQueryData(["tailoring", "queue"], previous);
      },
    });
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight">Review Queue</h1>
          <p className="text-muted-foreground">Tailored applications ready for review</p>
        </div>
        <Card>
          <CardContent className="p-0">
            <EmptyState
              icon={Sparkles}
              title="Review queue is empty"
              description="Pick a job from the Inbox and hit Generate Application — the tailored resume, cover, and outreach will land here ready to review."
              action={{ label: "Go to Inbox", href: "/dashboard/jobs" }}
            />
          </CardContent>
        </Card>
      </div>
    );
  }

  const review = selected || items[0];
  const status: string = review.approval_status;
  const isGenerating = status === "generating";
  const isFailed = status === "failed";
  const isReady = status === "ready";

  const counts = items.reduce(
    (acc: { ready: number; generating: number; failed: number }, it: any) => {
      if (it.approval_status === "ready") acc.ready++;
      else if (it.approval_status === "generating") acc.generating++;
      else if (it.approval_status === "failed") acc.failed++;
      return acc;
    },
    { ready: 0, generating: 0, failed: 0 },
  );

  const totalCount = counts.ready + counts.generating + counts.failed;
  return (
    <div className="space-y-4 ds-page-fade">
      {/* Page header — design pattern: h1 with mono accent count, single
          lede line, single right-aligned CTA. Counts breakdown + Clear
          failed live in the list-item dots, not in the header. */}
      <header
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
          marginBottom: 16,
        }}
      >
        <div style={{ minWidth: 0 }}>
          <h1
            className="ds-h1"
            style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}
          >
            <span>Review queue</span>
            {totalCount > 0 && (
              <span
                className="ds-mono"
                style={{
                  fontSize: 22,
                  fontWeight: 600,
                  color: "var(--ds-accent)",
                  letterSpacing: "-0.02em",
                }}
              >
                {totalCount}
              </span>
            )}
          </h1>
          <p
            style={{
              fontSize: 13,
              color: "var(--ds-fg-muted)",
              marginTop: 6,
              maxWidth: "65ch",
            }}
          >
            Tailored applications waiting on you. Approve, regenerate, or send.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {counts.failed > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleClearFailed}
              style={{ color: "var(--ds-fg-muted)" }}
              title="Discard all failed tailoring rows"
            >
              <XCircle className="h-3.5 w-3.5" />
              Clear {counts.failed} failed
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            nativeButton={false}
            render={<Link href="/dashboard/jobs" />}
          >
            <Sparkles className="h-3.5 w-3.5" />
            Tailor another job
          </Button>
        </div>
      </header>

      {/* 2-col layout from the Claude design: scrollable item list on the
          left (300px), editor on the right (1fr). Stacks at lg breakpoint. */}
      <div className="rev-grid">
        <aside className="rev-list">
          {items.map((item: any) => (
            <ReviewListItem
              key={item.id}
              item={item}
              active={review.id === item.id}
              onClick={() => setSelectedId(item.id)}
            />
          ))}
        </aside>

        <section className="rev-editor space-y-4 min-w-0">

      {/* Job sub-header — design pattern: small muted company line, h2
          title, ghost "View posting" button right-aligned. No Card
          wrapper, no badges, no location chip (the inbox row already
          surfaced those). Status + score live on the list-item dot. */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div style={{ minWidth: 0, flex: 1 }}>
          <div
            style={{
              fontSize: 12,
              color: "var(--ds-fg-muted)",
              fontWeight: 500,
            }}
          >
            {review.job?.company || "Unknown company"}
          </div>
          <h2
            className="ds-h2"
            style={{
              fontSize: 22,
              fontWeight: 600,
              letterSpacing: "-0.02em",
              lineHeight: 1.2,
              marginTop: 2,
              textWrap: "balance" as any,
            }}
          >
            {review.job?.title || "Untitled Job"}
          </h2>
        </div>
        {review.job?.job_url && (
          <Button
            variant="ghost"
            size="sm"
            nativeButton={false}
            render={<a href={review.job.job_url} target="_blank" rel="noopener" />}
            style={{ color: "var(--ds-fg-muted)" }}
          >
            <ExternalLink className="h-3.5 w-3.5" />
            View posting
          </Button>
        )}
      </div>

      {/* Application analysis — collapsed to a one-line chip strip so the
          insight is present without dominating the editor. The full
          matched/unmatched lists were valuable but rivaled the title
          card. Click to expand if you want the breakdown. */}
      {isReady && (review.keyword_matches || review.validation_notes) && (
        <AnalysisChips review={review} />
      )}

      {isGenerating && (
        <div
          style={{
            background: "var(--ds-bg-elev-1)",
            border: "1px solid var(--ds-accent-edge)",
            borderRadius: 8,
            padding: 22,
            marginTop: 18,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              marginBottom: 14,
            }}
          >
            <Sparkles
              className="h-4 w-4"
              style={{ color: "var(--ds-accent)" }}
            />
            <h3 className="ds-h3" style={{ fontSize: 14, fontWeight: 600 }}>
              Tailoring in progress
            </h3>
            <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12 }}>
              <ElapsedTime since={review.created_at} />
              <Button
                variant="ghost"
                size="xs"
                onClick={() => handleDelete(review)}
                style={{ color: "var(--ds-fg-muted)" }}
              >
                <XCircle className="h-3 w-3" />
                Cancel
              </Button>
            </span>
          </div>
          <ProgressTimeline currentStep={review.progress_step} />
          <p
            style={{
              fontSize: 13,
              color: "var(--ds-fg-muted)",
              marginTop: 16,
              lineHeight: 1.55,
            }}
          >
            Tailoring usually takes 30 to 60 seconds. You can leave this page —
            the toast on completion will bring you back.
          </p>
        </div>
      )}

      {isFailed && (
        <div
          style={{
            background: "var(--ds-bg-elev-1)",
            border: "1px solid #4a1a1a",
            borderRadius: 8,
            padding: 22,
            marginTop: 18,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
            <AlertCircle className="h-4 w-4" style={{ color: "#ef4444" }} />
            <h3 className="ds-h3" style={{ fontSize: 14, fontWeight: 600, color: "#ef4444" }}>
              Tailoring failed
            </h3>
          </div>
          <div
            className="ds-mono"
            style={{
              background: "var(--ds-bg-elev-2)",
              border: "1px solid var(--ds-line)",
              borderRadius: 6,
              padding: 12,
              fontSize: 12.5,
              color: "var(--ds-fg-muted)",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              marginBottom: 14,
            }}
          >
            {review.progress_step || "Unknown error"}
          </div>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => handleDelete(review)}
              style={{ color: "var(--ds-fg-muted)" }}
            >
              <XCircle className="h-3.5 w-3.5" />
              Discard
            </Button>
            <Button
              size="sm"
              onClick={() => handleRetry(review)}
              disabled={generate.isPending}
            >
              {generate.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              Try again
            </Button>
          </div>
        </div>
      )}

      {(isReady || status === "approved") && (
        <>
          <EditableMaterials
            review={review}
            draft={drafts[review.id]}
            onChange={(field, value) => updateDraft(review.id, field, value)}
            onAutoSave={() => {
              if (drafts[review.id]) handleSaveDraft(review);
            }}
            onCopy={copyText}
            copied={copied}
            onApprove={() => handleApprove(review)}
            approved={status === "approved"}
            approving={approve.isPending}
            onRegenerate={(section, guidance) => {
              return new Promise<void>((resolve, reject) => {
                regenerate.mutate(
                  { id: review.id, section, guidance },
                  {
                    onSuccess: () => {
                      // Server replaced the field — drop any local draft for it
                      // so the textarea picks up the new value cleanly.
                      setDrafts((d) => {
                        const cur = d[review.id];
                        if (!cur) return d;
                        const next: Draft = { ...cur };
                        delete next[section];
                        const empty = Object.keys(next).length === 0;
                        const nd = { ...d };
                        if (empty) delete nd[review.id];
                        else nd[review.id] = next;
                        return nd;
                      });
                      toast.success("Regenerated");
                      resolve();
                    },
                    onError: (err: any) => {
                      toast.error("Regenerate failed", { description: err?.message });
                      reject(err);
                    },
                  },
                );
              });
            }}
          />

          {/* Smaller footer row — per-tab Approve handles the approval gate,
              this row carries the destructive + apply-flow actions only. */}
          <div
            className="jd-actions"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              flexWrap: "wrap",
              marginTop: 16,
              paddingTop: 14,
              borderTop: "1px solid var(--ds-line)",
            }}
          >
            <Button
              variant="ghost"
              size="sm"
              onClick={() => handleDelete(review)}
              style={{ color: "var(--ds-fg-muted)" }}
            >
              <XCircle className="h-3.5 w-3.5" />
              Discard
            </Button>
            <Button
              variant="ghost"
              size="sm"
              nativeButton={false}
              render={<Link href={`/dashboard/review/${review.id}/print`} target="_blank" />}
              style={{ color: "var(--ds-fg-muted)" }}
            >
              <Download className="h-3.5 w-3.5" />
              Print / PDF
            </Button>
            <span style={{ flex: 1 }} />
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleOpenPosting(review)}
              disabled={!review.job_id}
              title="Opens the company's posting. Doesn't change your application status."
            >
              <ExternalLink className="h-3.5 w-3.5" />
              Open posting
            </Button>
            <Button
              size="sm"
              onClick={() => handleMarkApplied(review)}
              title="Click this AFTER you've actually submitted the application."
            >
              <Send className="h-3.5 w-3.5" />
              I applied
            </Button>
          </div>
        </>
      )}

        </section>
      </div>

      <style jsx>{`
        .rev-grid {
          display: grid;
          grid-template-columns: 300px minmax(0, 1fr);
          gap: 18px;
          align-items: start;
        }
        @media (max-width: 900px) {
          .rev-grid { grid-template-columns: 1fr; }
        }
        .rev-list {
          background: var(--ds-bg-elev-1);
          border: 1px solid var(--ds-line);
          border-radius: 8px;
          padding: 0;
          align-self: start;
          max-height: calc(100vh - 220px);
          overflow: auto;
          position: sticky;
          top: 16px;
        }
        @media (max-width: 900px) {
          .rev-list {
            position: static;
            max-height: 280px;
          }
        }
        .rev-editor { min-width: 0; }

        /* Tab strip — design pattern: thin underline rail spanning the
           editor, active tab gets a 1px accent underline. No icons,
           no filled background pill. */
        .rev-tabs {
          display: inline-flex;
          gap: 0;
          border-bottom: 1px solid var(--ds-line);
          margin-top: 18px;
        }
        .rev-tab {
          position: relative;
          padding: 12px 16px;
          font-size: 14px;
          color: var(--ds-fg-muted);
          background: transparent;
          border: 0;
          cursor: pointer;
          transition: color 120ms ease;
          display: inline-flex;
          align-items: center;
        }
        .rev-tab:hover { color: var(--ds-fg); }
        .rev-tab[data-active="true"] { color: var(--ds-fg); font-weight: 500; }
        .rev-tab[data-active="true"]::after {
          content: "";
          position: absolute;
          left: 8px;
          right: 8px;
          bottom: -1px;
          height: 1px;
          background: var(--ds-accent);
        }
      `}</style>
    </div>
  );
}

/* ============================================================
   ReviewListItem — left-sidebar entry per pending application.
   Status dot + title + company + score chip + updated-at. Click
   selects this item for the editor on the right.
   ============================================================ */
function ReviewListItem({
  item,
  active,
  onClick,
}: {
  item: any;
  active: boolean;
  onClick: () => void;
}) {
  const status: string = item.approval_status;
  const statusColor =
    status === "ready" ? "var(--ds-accent)"
    : status === "approved" ? "var(--ds-fg-muted)"
    : status === "generating" ? "var(--ds-fg-dim)"
    : status === "failed" ? "#ef4444"
    : "var(--ds-fg-faint)";
  const statusLabel =
    status === "ready" ? "ready"
    : status === "approved" ? "approved"
    : status === "generating" ? "generating"
    : status === "failed" ? "failed"
    : status;
  const score = item.job?.score?.overall_fit ?? null;
  const updatedAt = item.updated_at || item.created_at;
  const updatedAgo = updatedAt ? timeAgoShort(updatedAt) : "";
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      style={{
        display: "block",
        width: "100%",
        textAlign: "left",
        padding: "12px 14px",
        background: active ? "var(--ds-bg-elev-2)" : "transparent",
        borderLeft: active ? "2px solid var(--ds-accent)" : "2px solid transparent",
        borderBottom: "1px solid var(--ds-line-faint)",
        cursor: "pointer",
        minHeight: 56,
        transition: "background 120ms ease",
        color: "var(--ds-fg)",
      }}
      onMouseEnter={(e) => {
        if (!active) e.currentTarget.style.background = "var(--ds-bg-hover)";
      }}
      onMouseLeave={(e) => {
        if (!active) e.currentTarget.style.background = "transparent";
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div
            style={{
              fontSize: 13,
              fontWeight: 600,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {item.job?.title || "Untitled Job"}
          </div>
          <div
            style={{
              fontSize: 12,
              color: "var(--ds-fg-muted)",
              marginTop: 2,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {item.job?.company || "—"}
          </div>
        </div>
        {score != null && (
          <span
            className="ds-mono"
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: score >= 80 ? "var(--ds-accent)" : "var(--ds-fg-muted)",
              flexShrink: 0,
            }}
          >
            {Math.round(score)}
          </span>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: statusColor,
            boxShadow:
              status === "generating"
                ? "0 0 0 3px rgba(160,166,179,0.12)"
                : "none",
            flexShrink: 0,
          }}
        />
        <span
          className="ds-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: statusColor,
          }}
        >
          {statusLabel}
        </span>
        {updatedAgo && (
          <span
            className="ds-mono"
            style={{
              fontSize: 11,
              color: "var(--ds-fg-dim)",
              marginLeft: "auto",
            }}
          >
            {updatedAgo}
          </span>
        )}
      </div>
    </button>
  );
}

function timeAgoShort(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "now";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}d`;
  return `${Math.floor(d / 7)}w`;
}
