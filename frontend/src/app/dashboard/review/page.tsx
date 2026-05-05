"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Card, CardContent, CardHeader, CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import {
  CheckCircle2, XCircle, FileText, Mail, MessageSquare, Download,
  AlertCircle, Loader2, ExternalLink, MapPin, Building2, Globe, Copy, Check, Send,
  RefreshCw, Sparkles, Wand2,
} from "lucide-react";
import {
  useReviewQueue, useApproveTailored, useUpdateStatus, useGenerateTailored,
  useUpdateTailored, useRegenerateSection,
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

function EditableMaterials({
  review,
  draft,
  onChange,
  onSave,
  onDiscard,
  onCopy,
  copied,
  saving,
  onRegenerate,
}: {
  review: any;
  draft?: { tailored_summary?: string; cover_letter?: string; recruiter_message?: string };
  onChange: (field: EditableField, value: string) => void;
  onSave: () => void;
  onDiscard: () => void;
  onCopy: (text: string, label: string) => void;
  copied: string | null;
  saving: boolean;
  onRegenerate: (section: RegeneratableSection, guidance?: string) => Promise<void>;
}) {
  const dirty = draft !== undefined;
  const value = (field: EditableField, fallback: string | null) =>
    draft?.[field] ?? fallback ?? "";

  const fields: { key: EditableField; label: string; tab: string; placeholder: string }[] = [
    { key: "tailored_summary", label: "Resume", tab: "resume", placeholder: "No tailored summary generated yet." },
    { key: "cover_letter", label: "Cover", tab: "cover", placeholder: "No cover letter generated yet." },
    { key: "recruiter_message", label: "Outreach", tab: "outreach", placeholder: "No outreach message generated yet." },
  ];

  return (
    <Tabs defaultValue="resume">
      <TabsList className="w-full">
        <TabsTrigger value="resume" className="flex-1"><FileText className="h-3.5 w-3.5 mr-1.5" />Resume</TabsTrigger>
        <TabsTrigger value="cover" className="flex-1"><Mail className="h-3.5 w-3.5 mr-1.5" />Cover</TabsTrigger>
        <TabsTrigger value="outreach" className="flex-1"><MessageSquare className="h-3.5 w-3.5 mr-1.5" />Outreach</TabsTrigger>
      </TabsList>
      {fields.map((f) => {
        const v = value(f.key, review[f.key]);
        return (
          <TabsContent key={f.tab} value={f.tab}>
            <Card>
              <CardContent className="pt-4 space-y-2">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <span className="text-xs uppercase tracking-wider text-muted-foreground">
                    {dirty && draft?.[f.key] !== undefined ? "Edited" : "Editable"}
                  </span>
                  <div className="flex items-center gap-1 ml-auto">
                    <RegenerateControl
                      section={f.key}
                      onSubmit={onRegenerate}
                    />
                    {dirty && (
                      <>
                        <Button variant="ghost" size="sm" onClick={onDiscard} disabled={saving}>
                          Discard
                        </Button>
                        <Button size="sm" onClick={onSave} disabled={saving}>
                          {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                          Save edits
                        </Button>
                      </>
                    )}
                    {!dirty && (
                      <Button variant="ghost" size="sm" onClick={() => onCopy(v, f.tab)}>
                        {copied === f.tab ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                        {copied === f.tab ? "Copied" : "Copy"}
                      </Button>
                    )}
                  </div>
                </div>
                <textarea
                  value={v}
                  onChange={(e) => onChange(f.key, e.target.value)}
                  placeholder={f.placeholder}
                  spellCheck
                  className="block w-full min-h-[280px] resize-y rounded-lg bg-white/[0.02] border border-white/[0.04] focus:border-amber-500/30 focus:outline-none p-4 text-sm leading-relaxed font-sans whitespace-pre-line transition-colors"
                />
              </CardContent>
            </Card>
          </TabsContent>
        );
      })}
    </Tabs>
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
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
        <Wand2 className="h-3.5 w-3.5" />
        Regenerate
      </Button>
    );
  }

  return (
    <div className="flex items-center gap-1.5 rounded-md border border-amber-500/20 bg-amber-500/[0.04] pl-2 pr-1 py-1">
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
        className="bg-transparent text-sm placeholder:text-muted-foreground focus:outline-none w-56 sm:w-64"
      />
      <Button
        variant="ghost"
        size="xs"
        onClick={() => {
          setOpen(false);
          setGuidance("");
        }}
        disabled={busy}
      >
        Cancel
      </Button>
      <Button size="xs" onClick={() => fire(true)} disabled={busy}>
        {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Wand2 className="h-3 w-3" />}
        {guidance.trim() ? "Regenerate" : "Regenerate"}
      </Button>
    </div>
  );
}

function ProgressTimeline({ currentStep }: { currentStep: string | null }) {
  const idx = currentStep ? TAILORING_STEPS.indexOf(currentStep) : -1;
  return (
    <ul className="space-y-2">
      {TAILORING_STEPS.map((step, i) => {
        const done = idx > i;
        const active = idx === i;
        // "Answering screening questions" is conditional — show it dim when skipped.
        const optional = step === "Answering screening questions";
        return (
          <li key={step} className="flex items-center gap-2.5 text-sm">
            <span
              className={
                active
                  ? "h-2 w-2 rounded-full bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.6)]"
                  : done
                    ? "h-2 w-2 rounded-full bg-emerald-400"
                    : "h-2 w-2 rounded-full bg-white/10"
              }
            />
            <span
              className={
                active
                  ? "text-foreground font-medium"
                  : done
                    ? "text-muted-foreground line-through decoration-emerald-500/30"
                    : optional
                      ? "text-muted-foreground/40"
                      : "text-muted-foreground/60"
              }
            >
              {step}
            </span>
            {active && <Loader2 className="h-3 w-3 animate-spin text-amber-400" />}
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
   * One-button apply: opens the apply URL immediately so the user is in the form
   * while they decide. The status flip is delayed by the toast's undo window so
   * an accidental click can be reverted with no server round-trip wasted.
   */
  const handleOpenAndApply = async (review: any) => {
    if (!(await persistDraftIfDirty(review.id))) return;
    const applyUrl = review.job?.apply_url || review.job?.job_url;
    if (applyUrl) {
      window.open(applyUrl, "_blank", "noopener,noreferrer");
    }
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
          <CardContent className="py-12 text-center">
            <FileText className="h-10 w-10 mx-auto text-muted-foreground/20 mb-3" />
            <p className="text-muted-foreground">No applications pending review.</p>
            <p className="text-sm text-muted-foreground mt-1">
              Generate tailored materials from the Jobs Inbox.
            </p>
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

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight">Review Queue</h1>
          <p className="text-muted-foreground text-sm">
            {counts.ready > 0 && <span>{counts.ready} ready</span>}
            {counts.generating > 0 && (
              <span className={counts.ready > 0 ? "ml-2" : ""}>
                <Loader2 className="inline h-3 w-3 animate-spin text-amber-400 mr-1" />
                {counts.generating} generating
              </span>
            )}
            {counts.failed > 0 && (
              <span className="ml-2 text-red-400">
                {counts.failed} failed
              </span>
            )}
          </p>
        </div>
        {counts.failed > 0 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={handleClearFailed}
            className="text-muted-foreground hover:text-red-400"
            title="Discard all failed tailoring rows"
          >
            <XCircle className="h-3.5 w-3.5" />
            Clear {counts.failed} failed
          </Button>
        )}
      </div>

      {/* Tabs for each pending item */}
      {items.length > 1 && (
        <div className="flex gap-2 overflow-x-auto pb-2">
          {items.map((item: any) => {
            const itemStatus = item.approval_status;
            const active = review.id === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setSelectedId(item.id)}
                className={`shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  active
                    ? itemStatus === "failed"
                      ? "bg-red-500/10 text-red-400 border border-red-500/20"
                      : itemStatus === "generating"
                        ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                        : "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                    : "bg-white/[0.03] text-muted-foreground hover:bg-white/[0.06]"
                }`}
              >
                {itemStatus === "generating" && <Loader2 className="h-3 w-3 animate-spin" />}
                {itemStatus === "failed" && <AlertCircle className="h-3 w-3 text-red-400" />}
                <span>
                  {item.job?.title
                    ? `${item.job.title.slice(0, 30)}${item.job.title.length > 30 ? "..." : ""}`
                    : item.job_id?.slice(0, 8)}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {/* Job Header Card — meta wraps cleanly on mobile, action stays visible */}
      <Card className="border-amber-500/20">
        <CardContent className="py-4 space-y-3">
          <div className="flex items-start justify-between gap-3">
            <h2 className="text-lg sm:text-xl font-semibold leading-snug min-w-0">{review.job?.title || "Untitled Job"}</h2>
            {review.job?.job_url && (
              <Button variant="outline" size="sm" nativeButton={false} className="shrink-0"
                render={<a href={review.job.job_url} target="_blank" rel="noopener" />}>
                <ExternalLink className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">View posting</span>
              </Button>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
            <span className="flex items-center gap-1">
              <Building2 className="h-3.5 w-3.5" />
              {review.job?.company || "Unknown"}
            </span>
            {review.job?.location && (
              <span className="flex items-center gap-1">
                <MapPin className="h-3.5 w-3.5" />
                {review.job.location}
              </span>
            )}
            {review.job?.remote_type && review.job.remote_type !== "unknown" && (
              <Badge variant="secondary" className="text-xs bg-emerald-500/10 text-emerald-400">
                <Globe className="h-3 w-3 mr-0.5" />
                {review.job.remote_type === "full_remote" ? "Remote"
                  : review.job.remote_type === "hybrid" ? "Hybrid"
                  : review.job.remote_type === "onsite" ? "On-site"
                  : review.job.remote_type}
              </Badge>
            )}
            {review.job?.salary_text && (
              <span className="text-emerald-400 font-medium">{review.job.salary_text}</span>
            )}
          </div>
        </CardContent>
      </Card>

      {isGenerating && (
        <Card className="border-amber-500/20 bg-gradient-to-br from-amber-500/[0.03] to-transparent">
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-amber-400" />
              Tailoring in progress
              <span className="ml-auto flex items-center gap-3">
                <ElapsedTime since={review.created_at} />
                <Button
                  variant="ghost"
                  size="xs"
                  onClick={() => handleDelete(review)}
                  className="text-muted-foreground hover:text-red-400"
                >
                  <XCircle className="h-3 w-3" />
                  Cancel
                </Button>
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ProgressTimeline currentStep={review.progress_step} />
            <p className="text-sm text-muted-foreground mt-4 leading-relaxed">
              Tailoring usually takes 30 to 60 seconds. You can leave this page —
              the toast on completion will bring you back.
            </p>
          </CardContent>
        </Card>
      )}

      {isFailed && (
        <Card className="border-red-500/20 bg-gradient-to-br from-red-500/[0.03] to-transparent">
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2 text-red-400">
              <AlertCircle className="h-4 w-4" />
              Tailoring failed
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-lg bg-red-500/[0.04] border border-red-500/10 p-3 text-sm text-red-300/90 font-mono whitespace-pre-wrap break-words">
              {review.progress_step || "Unknown error"}
            </div>
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => handleDelete(review)}
                className="text-muted-foreground"
              >
                <XCircle className="h-3.5 w-3.5" />
                Discard
              </Button>
              <Button
                size="sm"
                onClick={() => handleRetry(review)}
                disabled={generate.isPending}
              >
                {generate.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                Try again
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {isReady && (
      <div className="grid gap-4 lg:grid-cols-2 items-start">
        {/* Left: Keywords + Fit */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Application Analysis</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {review.keyword_matches && (
              <>
                <div>
                  <span className="text-xs text-muted-foreground">Matched keywords:</span>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {(review.keyword_matches.matched || []).map((kw: string) => (
                      <Badge key={kw} variant="secondary" className="text-xs bg-emerald-500/10 text-emerald-400">{kw}</Badge>
                    ))}
                  </div>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">Gaps:</span>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {(review.keyword_matches.unmatched || []).map((kw: string) => (
                      <Badge key={kw} variant="secondary" className="text-xs bg-amber-500/10 text-amber-400">{kw}</Badge>
                    ))}
                  </div>
                </div>
              </>
            )}
            {review.validation_notes && (
              <>
                <Separator />
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <div className="flex items-center gap-1.5 mb-1.5">
                      <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                      <span className="text-xs font-medium">Strengths</span>
                    </div>
                    <ul className="space-y-1">
                      {(review.validation_notes.strongest_matches || []).map((s: string) => (
                        <li key={s} className="text-xs text-muted-foreground">{s}</li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <div className="flex items-center gap-1.5 mb-1.5">
                      <AlertCircle className="h-3.5 w-3.5 text-amber-400" />
                      <span className="text-xs font-medium">Gaps</span>
                    </div>
                    <ul className="space-y-1">
                      {(review.validation_notes.gaps || []).map((g: string) => (
                        <li key={g} className="text-xs text-muted-foreground">{g}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* Right: Tailored Materials */}
        <div className="space-y-4">
          <EditableMaterials
            review={review}
            draft={drafts[review.id]}
            onChange={(field, value) => updateDraft(review.id, field, value)}
            onSave={() => handleSaveDraft(review)}
            onDiscard={() => clearDraft(review.id)}
            onCopy={copyText}
            copied={copied}
            saving={updateTailored.isPending}
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

          {/* Actions — wrap on narrow widths so the primary 'Open & Apply'
              button is never clipped off the right edge. */}
          <Card>
            <CardContent className="flex flex-wrap items-center gap-2 py-3 sm:justify-between">
              <div className="flex gap-2">
                <Button variant="outline" size="sm" nativeButton={false}
                  render={<Link href={`/dashboard/review/${review.id}/print`} target="_blank" />}>
                  <Download className="h-3.5 w-3.5" /> Print / PDF
                </Button>
              </div>
              <div className="flex flex-wrap gap-2 ml-auto">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleDelete(review)}
                  className="text-red-400 hover:text-red-300 hover:border-red-500/30"
                >
                  <XCircle className="h-3.5 w-3.5" />
                  Discard
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleApprove(review)}
                  disabled={approve.isPending}
                >
                  {approve.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <CheckCircle2 className="h-3.5 w-3.5" />
                  )}
                  Approve
                </Button>
                <Button
                  size="sm"
                  onClick={() => handleOpenAndApply(review)}
                  disabled={!review.job?.apply_url && !review.job?.job_url}
                  title={
                    !review.job?.apply_url && !review.job?.job_url
                      ? "No application link available"
                      : "Opens the apply page and marks Applied (with 5s undo)"
                  }
                >
                  <Send className="h-3.5 w-3.5" />
                  Open & Apply
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
      )}
    </div>
  );
}
