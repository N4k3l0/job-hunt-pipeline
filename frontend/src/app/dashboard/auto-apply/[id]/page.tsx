"use client";

import { use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Check, CheckCircle2, Copy, ExternalLink, FileText, Loader2, Pencil, Puzzle, RefreshCw, Wand2,
} from "lucide-react";
import {
  useAutoApplication, useCancelAutoApplication, useMarkAutoApplicationSent, usePrepareAutoApplication,
  useSaveAutoApplyAnswers,
} from "@/hooks/use-api";
import { useExtensionInstalled } from "@/hooks/use-extension";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api-client";
import { askExtension } from "@/lib/extension";
import { AutoApplyStatusPill } from "@/components/auto-apply-status";
import { OperationProgress } from "@/components/operation-progress";
import type { AutoApplyField, AutoApplyFill, AutoApplyValue } from "@/lib/types";

// How long the page keeps checking whether the form was sent.
const WATCH_MS = 20 * 60 * 1000;

const ATS_NAMES: Record<string, string> = { greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby" };

const SOURCE_LABELS: Record<string, string> = {
  profile: "From your profile",
  saved: "Your earlier answer",
  default: "Filled in for you",
  suggested: "Suggested",
  drafted: "Drafted for you",
  user: "Your answer",
};

function isEmpty(value: AutoApplyValue | undefined) {
  return value === null || value === undefined || value === "" || (Array.isArray(value) && value.length === 0);
}

function displayValue(field: AutoApplyField, value: AutoApplyValue | undefined): string {
  if (isEmpty(value)) return "";
  if (field.type === "file") return field.kind === "resume" ? "Your latest resume" : "File";
  if (field.type === "boolean") return value ? "Yes" : "No";
  if (field.options) {
    const values = Array.isArray(value) ? value : [String(value)];
    return values.map((v) => field.options!.find((o) => o.value === v)?.label ?? v).join(", ");
  }
  return String(value);
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  background: "var(--ds-bg-elev-1)",
  border: "1px solid var(--ds-line)",
  borderRadius: "var(--ds-r-pill)",
  color: "var(--ds-fg)",
  fontSize: 13,
  fontFamily: "inherit",
  padding: "8px 12px",
  outline: "none",
};

function FieldInput({
  field,
  value,
  onChange,
}: {
  field: AutoApplyField;
  value: AutoApplyValue | undefined;
  onChange: (value: AutoApplyValue) => void;
}) {
  const id = `field-${field.key}`;
  if (field.type === "file") {
    return (
      <div className="ds-muted flex items-center" style={{ gap: 6, fontSize: 13 }}>
        <FileText className="h-4 w-4" />
        {field.kind === "resume"
          ? isEmpty(value) ? "Upload your resume on your profile first." : "Your latest resume is attached."
          : "The app can't attach this file yet. Open the form to add it yourself."}
      </div>
    );
  }
  if (field.type === "boolean") {
    return (
      <div className="flex" style={{ gap: 6 }}>
        {[true, false].map((option) => (
          <button
            key={String(option)}
            type="button"
            className="ds-chip"
            data-active={value === option}
            onClick={() => onChange(option)}
          >
            {option ? "Yes" : "No"}
          </button>
        ))}
      </div>
    );
  }
  if (field.type === "select" && field.options) {
    if (field.options.length <= 6) {
      return (
        <div className="flex flex-wrap" style={{ gap: 6 }}>
          {field.options.map((o) => (
            <button
              key={o.value}
              type="button"
              className="ds-chip"
              data-active={value === o.value}
              onClick={() => onChange(o.value)}
              style={{ height: "auto", minHeight: 30, padding: "5px 10px", whiteSpace: "normal", textAlign: "left" }}
            >
              {o.label}
            </button>
          ))}
        </div>
      );
    }
    return (
      <select id={id} value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value || null)} style={inputStyle}>
        <option value="">Choose…</option>
        {field.options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    );
  }
  if (field.type === "multiselect" && field.options) {
    const selected = Array.isArray(value) ? value : [];
    return (
      <div className="flex flex-wrap" style={{ gap: 6 }}>
        {field.options.map((o) => {
          const active = selected.includes(o.value);
          return (
            <button
              key={o.value}
              type="button"
              className="ds-chip"
              data-active={active}
              onClick={() => onChange(active ? selected.filter((v) => v !== o.value) : [...selected, o.value])}
              style={{ height: "auto", minHeight: 30, padding: "5px 10px", whiteSpace: "normal", textAlign: "left" }}
            >
              {active && <Check className="h-3.5 w-3.5 shrink-0" />}
              {o.label}
            </button>
          );
        })}
      </div>
    );
  }
  if (field.type === "textarea") {
    return (
      <textarea
        id={id}
        value={(value as string) ?? ""}
        onChange={(e) => onChange(e.target.value)}
        rows={5}
        style={{ ...inputStyle, borderRadius: "var(--ds-r-card)", resize: "vertical", lineHeight: 1.5 }}
      />
    );
  }
  const htmlType = { email: "email", phone: "tel", url: "url", number: "number", date: "date" }[field.type as string] ?? "text";
  return (
    <input
      id={id}
      type={htmlType}
      value={value === null || value === undefined ? "" : String(value)}
      onChange={(e) => onChange(field.type === "number" && e.target.value !== "" ? Number(e.target.value) : e.target.value)}
      style={{ ...inputStyle, height: 36 }}
    />
  );
}

function AnswerMeta({ field }: { field: AutoApplyField }) {
  const answer = field.answer;
  if (!answer?.note && !answer?.source) return null;
  return (
    <div className="ds-dim" style={{ fontSize: 12, marginTop: 6 }}>
      {answer.source && <span className="ds-accent-fg">{SOURCE_LABELS[answer.source] ?? answer.source}</span>}
      {answer.source && answer.note && " · "}
      {answer.note}
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  if (!text) return null;
  return (
    <button
      type="button"
      className="ds-btn ghost sm"
      onClick={() => {
        navigator.clipboard.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
      title="Copy this answer"
    >
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}

function Question({
  field,
  value,
  onChange,
  editable,
  highlighted,
}: {
  field: AutoApplyField;
  value: AutoApplyValue | undefined;
  onChange: (value: AutoApplyValue) => void;
  editable: boolean;
  highlighted: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const showInput = editable && (field.needs_attention || editing);
  const text = displayValue(field, value);
  return (
    <div
      style={{
        padding: "14px 16px",
        borderTop: "1px solid var(--ds-line)",
        background: highlighted ? "var(--ds-accent-soft)" : undefined,
      }}
    >
      <div className="flex items-start justify-between" style={{ gap: 12 }}>
        <label htmlFor={`field-${field.key}`} style={{ fontSize: 14, fontWeight: 500, lineHeight: 1.4 }}>
          {field.label}
          {field.required && <span className="ds-dim"> *</span>}
        </label>
        {!showInput && (
          <div className="flex shrink-0" style={{ gap: 2 }}>
            {field.type !== "file" && field.type !== "boolean" && !field.options && <CopyButton text={text} />}
            {editable && field.type !== "file" && (
              <button type="button" className="ds-btn ghost sm" onClick={() => setEditing(true)} title="Change this answer">
                <Pencil className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        )}
      </div>
      {field.description && (showInput || field.kind === "agreement") && (
        <div
          className="ds-muted"
          style={{ fontSize: 12, whiteSpace: "pre-line", marginTop: 6, maxHeight: 160, overflowY: "auto", lineHeight: 1.5 }}
        >
          {field.description}
        </div>
      )}
      <div style={{ marginTop: 8 }}>
        {showInput ? (
          <FieldInput field={field} value={value} onChange={onChange} />
        ) : (
          <div className={text ? "" : "ds-dim"} style={{ fontSize: 13, whiteSpace: "pre-line" }}>
            {text || "Left blank"}
          </div>
        )}
      </div>
      <AnswerMeta field={field} />
    </div>
  );
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <div className="flex items-baseline justify-between" style={{ gap: 12 }}>
        <h2 className="ds-h3">{title}</h2>
        {hint && <span className="ds-dim" style={{ fontSize: 12 }}>{hint}</span>}
      </div>
      <div className="ds-card" style={{ overflow: "hidden", marginTop: 8 }}>
        <div style={{ marginTop: -1 }}>{children}</div>
      </div>
    </section>
  );
}

export default function AutoApplicationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [watchingSince, setWatchingSince] = useState<number | null>(null);
  const watching = watchingSince !== null && Date.now() - watchingSince < WATCH_MS;
  const { data: application, isLoading, error } = useAutoApplication(id, { watch: watching });
  const save = useSaveAutoApplyAnswers(id);
  const cancel = useCancelAutoApplication(id);
  const prepare = usePrepareAutoApplication();
  const markSent = useMarkAutoApplicationSent(id);
  const extensionInstalled = useExtensionInstalled();
  const toast = useToast();
  const qc = useQueryClient();

  const [values, setValues] = useState<Record<string, AutoApplyValue>>({});
  const [edited, setEdited] = useState<Set<string>>(new Set());
  const [problemKeys, setProblemKeys] = useState<string[]>([]);
  const [filling, setFilling] = useState(false);

  // The extension reports the form as sent; tell the user once it shows up.
  useEffect(() => {
    if (!watching || application?.status !== "submitted") return;
    setWatchingSince(null);
    qc.invalidateQueries({ queryKey: ["auto-apply"], exact: true });
    qc.invalidateQueries({ queryKey: ["jobs"] });
    qc.invalidateQueries({ queryKey: ["tracking"] });
    toast.success("Application sent", { description: "Now tracked in Applications." });
  }, [watching, application?.status, qc, toast]);

  // Reset local answers whenever the server copy changes (load, save).
  useEffect(() => {
    if (!application) return;
    setValues(Object.fromEntries(application.fields.map((f) => [f.key, f.answer?.value ?? null])));
    setEdited(new Set());
  }, [application]);

  const groups = useMemo(() => {
    const fields = application?.fields ?? [];
    const answered = (f: AutoApplyField) => !isEmpty(f.answer?.value);
    return {
      needsYou: fields.filter((f) => f.needs_attention),
      filled: fields.filter((f) => !f.needs_attention && f.group === "application" && answered(f)),
      voluntary: fields.filter((f) => !f.needs_attention && f.group === "voluntary"),
      blank: fields.filter((f) => !f.needs_attention && f.group === "application" && !answered(f)),
    };
  }, [application]);

  if (isLoading) {
    return (
      <div className="flex justify-center py-16">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (error || !application) {
    return (
      <div className="ds-root space-y-4">
        <Link href="/dashboard/auto-apply" className="ds-btn ghost" style={{ paddingLeft: 0 }}>
          <ArrowLeft className="h-3.5 w-3.5" /> Apply for me
        </Link>
        <p className="ds-muted">Application not found.</p>
      </div>
    );
  }

  const editable = application.status === "needs_you" || application.status === "queued";
  const setValue = (key: string, value: AutoApplyValue) => {
    setValues((current) => ({ ...current, [key]: value }));
    setEdited((current) => new Set(current).add(key));
    setProblemKeys((current) => current.filter((k) => k !== key));
  };

  function submit(approve: boolean) {
    const keys = new Set(edited);
    if (approve) {
      const missing = groups.needsYou.filter((f) => f.required && isEmpty(values[f.key]));
      if (missing.length) {
        setProblemKeys(missing.map((f) => f.key));
        toast.error(`${missing.length} ${missing.length === 1 ? "question still needs" : "questions still need"} an answer`);
        return;
      }
      // Sending a suggested or drafted answer back confirms it.
      groups.needsYou.forEach((f) => keys.add(f.key));
    }
    const answers = Object.fromEntries(
      [...keys].filter((k) => application!.fields.some((f) => f.key === k && f.type !== "file")).map((k) => [k, values[k] ?? null]),
    );
    save.mutate(
      { answers, approve },
      {
        onSuccess: () => {
          setProblemKeys([]);
          toast.success(approve ? "Answers approved" : "Saved");
        },
        onError: (e: Error & { detail?: { fields?: string[] } }) => {
          const fields = e.detail?.fields;
          if (Array.isArray(fields)) setProblemKeys(fields);
          toast.error(approve ? "Couldn't approve" : "Couldn't save", { description: e?.message });
        },
      },
    );
  }

  async function fillInForm() {
    setFilling(true);
    try {
      const details = await api.get<AutoApplyFill>(`/api/v1/auto-apply/${id}/fill`);
      // The extension downloads the resume before opening the form.
      const reply = await askExtension("fill-form", { application: details }, 20000);
      if (!reply) throw new Error("The extension didn't answer. Reload this page and try again.");
      if (reply.error) throw new Error(reply.error);
      setWatchingSince(Date.now());
      toast.success("Opening the form", { description: "Look over the answers, then press Submit on the form." });
    } catch (e) {
      toast.error("Couldn't fill in the form", { description: e instanceof Error ? e.message : undefined });
    } finally {
      setFilling(false);
    }
  }

  function markApplied() {
    markSent.mutate(undefined, {
      onSuccess: () => {
        setWatchingSince(null);
        toast.success("Marked as sent", { description: "Now tracked in Applications." });
      },
      onError: (e) => toast.error("Couldn't mark as sent", { description: e.message }),
    });
  }

  const renderQuestion = (field: AutoApplyField) => (
    <Question
      key={field.key}
      field={field}
      value={values[field.key]}
      onChange={(v) => setValue(field.key, v)}
      editable={editable}
      highlighted={problemKeys.includes(field.key)}
    />
  );

  const total = application.fields.length;
  const job = application.job;

  return (
    <div className="ds-root ds-page-fade" style={{ background: "var(--ds-bg)" }}>
      <div className="space-y-6" style={{ maxWidth: 820, margin: "0 auto", paddingBottom: 96 }}>
        <Link href="/dashboard/auto-apply" className="ds-btn ghost" style={{ paddingLeft: 0, width: "fit-content" }}>
          <ArrowLeft className="h-3.5 w-3.5" /> Apply for me
        </Link>

        <div className="space-y-3">
          <div className="ds-muted" style={{ fontSize: 14, fontWeight: 500 }}>{job?.company}</div>
          <h1 className="ds-h1" style={{ textWrap: "balance" }}>{job?.title}</h1>
          <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
            <AutoApplyStatusPill status={application.status} />
            {application.ats && <span className="ds-pill">{ATS_NAMES[application.ats]}</span>}
            {job?.location && <span className="ds-pill">{job.location}</span>}
          </div>
          <div className="flex flex-wrap" style={{ gap: 8, paddingTop: 4 }}>
            {application.form_url && (
              <a href={application.form_url} target="_blank" rel="noopener noreferrer" className="ds-btn">
                <ExternalLink className="h-4 w-4" /> Open the form
              </a>
            )}
            <Link href={`/dashboard/jobs/${application.job_id}`} className="ds-btn ghost">View job</Link>
          </div>
        </div>

        {/* What's happening, and what the user can do about it. */}
        <div className="ds-card" style={{ padding: 16, fontSize: 14, lineHeight: 1.5 }}>
          {application.status === "needs_you" && (
            <p>
              <strong>{groups.needsYou.length} of {total}</strong> questions need you. The app filled in the rest from
              your profile. Check the answers below and approve them, then the extension fills in the company&apos;s
              form for you.
            </p>
          )}
          {application.status === "queued" && (
            <div className="space-y-3">
              <p>
                <CheckCircle2 className="inline h-4 w-4 ds-accent-fg" style={{ marginRight: 6, verticalAlign: -3 }} />
                {extensionInstalled === false
                  ? "Answers approved. Add the Job Hunt extension to Chrome and it fills in the company's form for you. You look it over and press Submit."
                  : "Answers approved. Fill in the form opens the company's form in a new tab with your answers filled in. Look it over, then press Submit there."}
              </p>
              <div className="flex flex-wrap" style={{ gap: 8 }}>
                {extensionInstalled === false ? (
                  <Link href="/dashboard/extension" className="ds-btn primary">
                    <Puzzle className="h-4 w-4" /> Add the extension
                  </Link>
                ) : (
                  <button
                    type="button"
                    className="ds-btn primary"
                    onClick={fillInForm}
                    disabled={filling || extensionInstalled === null}
                  >
                    {filling ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
                    Fill in the form
                  </button>
                )}
                <button type="button" className="ds-btn" onClick={markApplied} disabled={markSent.isPending}>
                  {markSent.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                  I sent it myself
                </button>
              </div>
              {watching && (
                <p className="ds-dim flex items-center" style={{ fontSize: 13, gap: 6 }}>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Waiting for you to press Submit on the form. This page updates once it&apos;s sent.
                </p>
              )}
            </div>
          )}
          {application.status === "submitted" && (
            <p>Sent{application.submitted_at ? ` on ${new Date(application.submitted_at).toLocaleString()}` : ""}.</p>
          )}
          {(application.status === "failed" || application.status === "unsupported") && (
            <div className="space-y-3">
              <p>{application.error ?? "The app couldn't prepare this application."}</p>
              {application.status === "failed" && (
                <button
                  type="button"
                  className="ds-btn"
                  onClick={() => prepare.mutate(application.job_id)}
                  disabled={prepare.isPending}
                >
                  {prepare.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  Try again
                </button>
              )}
            </div>
          )}
          {application.status === "cancelled" && (
            <div className="space-y-3">
              <p>You stopped this application.</p>
              <button
                type="button"
                className="ds-btn"
                onClick={() => prepare.mutate(application.job_id)}
                disabled={prepare.isPending}
              >
                {prepare.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                Prepare again
              </button>
            </div>
          )}
          <OperationProgress
            active={prepare.isPending}
            stages={[
              { label: "Reading the application form", durationMs: 2000 },
              { label: "Filling in from your profile", durationMs: 1000 },
              { label: "Drafting answers to the rest", durationMs: 9000 },
            ]}
          />
        </div>

        {groups.needsYou.length > 0 && (
          <Section title="Needs you" hint="Answer these, or confirm what's suggested">
            {groups.needsYou.map(renderQuestion)}
          </Section>
        )}
        {groups.filled.length > 0 && (
          <Section title="Filled in for you" hint="Change anything that's wrong">
            {groups.filled.map(renderQuestion)}
          </Section>
        )}
        {groups.voluntary.length > 0 && (
          <Section title="Voluntary questions" hint="Declined where the form allows it">
            {groups.voluntary.map(renderQuestion)}
          </Section>
        )}
        {groups.blank.length > 0 && (
          <Section title="Optional, left blank">
            {groups.blank.map(renderQuestion)}
          </Section>
        )}

        {editable && (
          <div
            className="flex flex-wrap items-center justify-between"
            style={{
              position: "sticky",
              bottom: 12,
              gap: 8,
              padding: 12,
              background: "var(--ds-bg-elev-2)",
              border: "1px solid var(--ds-line-strong)",
              borderRadius: "var(--ds-r-lg)",
            }}
          >
            <button
              type="button"
              className="ds-btn ghost"
              onClick={() => cancel.mutate(undefined, { onError: (e) => toast.error("Couldn't stop", { description: e.message }) })}
              disabled={cancel.isPending}
            >
              Stop this application
            </button>
            <div className="flex" style={{ gap: 8 }}>
              {edited.size > 0 && (
                <button type="button" className="ds-btn" onClick={() => submit(false)} disabled={save.isPending}>
                  Save
                </button>
              )}
              {(application.status === "needs_you" || edited.size > 0) && (
                <button type="button" className="ds-btn primary" onClick={() => submit(true)} disabled={save.isPending}>
                  {save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                  Approve answers
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
