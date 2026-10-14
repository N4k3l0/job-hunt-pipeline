"use client";

import { useEffect, useRef, useState } from "react";
import { Check, CheckCircle2, Copy, ExternalLink, Loader2, RefreshCw, Search, UserSearch } from "lucide-react";
import { useOutreachNote, usePrepareOutreachNote, useUpdateOutreachNote } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";
import { OperationProgress } from "@/components/operation-progress";

const STAGES = [
  {
    label: "Looking for the hiring manager",
    durationMs: 25000,
    tip: "Then the head of the team, then a recruiter, from the company's own pages and LinkedIn.",
  },
  { label: "Writing your note", durationMs: 8000, tip: "From your real work, short enough for a LinkedIn connection request." },
  { label: "Checking the wording", durationMs: 5000, tip: "Plain English, no long dashes." },
];

const textareaStyle: React.CSSProperties = {
  width: "100%",
  background: "var(--ds-bg-elev-1)",
  border: "1px solid var(--ds-line)",
  borderRadius: "var(--ds-r-card)",
  color: "var(--ds-fg)",
  fontSize: 14,
  fontFamily: "inherit",
  lineHeight: 1.5,
  padding: "10px 12px",
  outline: "none",
  resize: "vertical",
};

/** After applying: who to write to at the company, and a short note the
 *  user sends from their own LinkedIn. The app never sends it: LinkedIn
 *  doesn't allow that. On the application page and the job page, once the
 *  application is sent; the daily email links here (#message). */
export function MessageStep({ jobId }: { jobId: string }) {
  const toast = useToast();
  const { data: note } = useOutreachNote(jobId);
  const prepare = usePrepareOutreachNote(jobId);
  const update = useUpdateOutreachNote(jobId);
  // What the user typed, until it's saved; null shows the saved note.
  const [draft, setDraft] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const started = useRef(false);
  const card = useRef<HTMLElement>(null);
  const { mutate: runPrepare } = prepare;

  // Sent in the last week and nothing written yet: write it now, while the
  // user is here. Older ones wait for the button (each costs a little AI).
  useEffect(() => {
    if (!note?.auto || started.current) return;
    started.current = true;
    runPrepare({}, { onError: (e) => toast.error("Couldn't write the note", { description: e.message }) });
  }, [note?.auto, runPrepare, toast]);

  // Links from the daily email land here.
  const canMessage = !!note?.can_message;
  useEffect(() => {
    if (canMessage && window.location.hash === "#message") {
      card.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [canMessage]);

  if (!note || !note.can_message) return null;

  const company = note.company || "the company";
  const contact = note.contact;
  const firstName = contact?.name?.split(" ")[0];
  const text = draft ?? note.message ?? "";
  const edited = draft !== null && draft !== (note.message ?? "");
  const tooLong = text.length > note.max_chars;

  const write = (how: { lookAgain?: boolean; rewrite?: boolean } = {}) =>
    prepare.mutate(
      how,
      {
        onSuccess: () => setDraft(null),
        onError: (e) => toast.error("Couldn't write the note", { description: e.message }),
      },
    );
  const save = (body: { message?: string; status?: "drafted" | "sent" | "skipped" }) =>
    update.mutate(body, {
      onSuccess: () => setDraft(null),
      onError: (e) => toast.error("Couldn't save that", { description: e.message }),
    });
  const setStatus = (status: "drafted" | "sent" | "skipped") => save({ status, ...(edited ? { message: text } : {}) });
  const copy = () =>
    navigator.clipboard.writeText(text).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      },
      () => toast.error("Couldn't copy", { description: "Select the note and copy it yourself." }),
    );

  let body: React.ReactNode;
  if (prepare.isPending) {
    body = <OperationProgress active title="Finding someone to write to" stages={STAGES} />;
  } else if (note.status === "sent") {
    body = (
      <div className="space-y-2" style={{ fontSize: 14 }}>
        <p>
          <CheckCircle2 className="inline h-4 w-4" style={{ color: "var(--ds-ok)", verticalAlign: -3 }} /> You sent a
          note{contact?.name ? ` to ${contact.name}` : ""}
          {note.sent_at ? ` on ${new Date(note.sent_at).toLocaleDateString()}` : ""}. If they reply, move the
          application to Interviewing on the Applications page.
        </p>
        <button type="button" className="ds-btn ghost sm" onClick={() => setStatus("drafted")} disabled={update.isPending}>
          Not sent after all
        </button>
      </div>
    );
  } else if (note.status === "skipped") {
    body = (
      <div className="flex flex-wrap items-center" style={{ gap: 10, fontSize: 14 }}>
        <span className="ds-muted">Skipped. You can still write to someone at {company}.</span>
        <button
          type="button"
          className="ds-btn sm"
          onClick={() => (note.message ? setStatus("drafted") : write())}
          disabled={update.isPending}
        >
          Write a note
        </button>
      </div>
    );
  } else if (!note.message) {
    body = (
      <div className="space-y-3">
        <p className="ds-muted" style={{ fontSize: 14 }}>
          A short note to the right person gets your application looked at more often than waiting does. The app
          looks for the hiring manager for this role, then the head of the team, then a recruiter, and writes the note
          from your real work. It uses about 15 cents of AI.
        </p>
        {prepare.isError && (
          <p className="text-warn" style={{ fontSize: 13 }}>{prepare.error.message}</p>
        )}
        <div className="flex flex-wrap" style={{ gap: 8 }}>
          <button type="button" className="ds-btn primary" onClick={() => write()}>
            <UserSearch className="h-4 w-4" />
            {prepare.isError ? "Try again" : "Find someone and write the note"}
          </button>
          <button type="button" className="ds-btn ghost" onClick={() => setStatus("skipped")} disabled={update.isPending}>
            Skip
          </button>
        </div>
      </div>
    );
  } else {
    body = (
      <div className="space-y-3">
        {contact ? (
          <div className="space-y-1">
            <div style={{ fontSize: 15, fontWeight: 600 }}>{contact.name ?? `Someone at ${company}`}</div>
            {contact.title && <div className="ds-muted" style={{ fontSize: 13 }}>{contact.title}</div>}
            {contact.confidence === "low" && (
              <p className="text-warn" style={{ fontSize: 13 }}>
                The app isn&apos;t sure this is the right person. Check their profile first.
              </p>
            )}
            {contact.source_notes && <p className="ds-dim" style={{ fontSize: 12 }}>{contact.source_notes}</p>}
          </div>
        ) : (
          <p className="ds-muted" style={{ fontSize: 14 }}>
            The app couldn&apos;t find the right person this time. Search LinkedIn for people at {company}, or look
            again.
          </p>
        )}

        {note.linkedin_job_url && (
          <p className="ds-muted" style={{ fontSize: 13 }}>
            This job is on LinkedIn. Open it and look for <strong>Meet the hiring team</strong>: if someone is listed,
            they posted the job, so write to them instead.{" "}
            <a href={note.linkedin_job_url} target="_blank" rel="noopener noreferrer" className="ds-accent-fg">
              Open the job on LinkedIn
            </a>
          </p>
        )}

        <div className="space-y-1">
          <textarea
            value={text}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => edited && save({ message: text })}
            rows={5}
            style={textareaStyle}
            aria-label="Your note"
          />
          <div className="flex flex-wrap justify-between" style={{ gap: 8, fontSize: 12 }}>
            <span className="ds-dim">Edit anything. It&apos;s your note.</span>
            <span className={tooLong ? "text-warn" : "ds-dim"}>
              {text.length} / {note.max_chars}
              {tooLong ? ". LinkedIn cuts off the rest" : ""}
            </span>
          </div>
          {!edited && note.problems.length > 0 && (
            <ul className="text-warn" style={{ fontSize: 13, paddingLeft: 18, listStyle: "disc" }}>
              {note.problems.map((p) => <li key={p}>{p}</li>)}
            </ul>
          )}
        </div>

        <p className="ds-muted" style={{ fontSize: 13 }}>
          On {firstName ? `${firstName}'s` : "their"} profile, press <strong>Connect</strong>, then{" "}
          <strong>Add a note</strong>, and paste it. No Connect button? It&apos;s under <strong>More</strong>.
        </p>

        <div className="flex flex-wrap" style={{ gap: 8 }}>
          <button type="button" className="ds-btn primary" onClick={copy}>
            {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
            {copied ? "Copied" : "Copy the note"}
          </button>
          <a
            href={contact?.linkedin_url ?? note.people_search_url}
            target="_blank"
            rel="noopener noreferrer"
            className="ds-btn"
          >
            {contact?.linkedin_url ? <ExternalLink className="h-4 w-4" /> : <Search className="h-4 w-4" />}
            {contact?.linkedin_url
              ? `Open ${firstName ? `${firstName}'s` : "their"} LinkedIn`
              : `Search LinkedIn for people at ${company}`}
          </a>
          <button type="button" className="ds-btn" onClick={() => setStatus("sent")} disabled={update.isPending}>
            <CheckCircle2 className="h-4 w-4" />
            I sent it
          </button>
          <button type="button" className="ds-btn ghost" onClick={() => setStatus("skipped")} disabled={update.isPending}>
            Skip
          </button>
          <button
            type="button"
            className="ds-btn ghost"
            onClick={() => write({ rewrite: true })}
            title="A new note to the same person, about 2 cents of AI"
          >
            <RefreshCw className="h-4 w-4" />
            Write it again
          </button>
          <button
            type="button"
            className="ds-btn ghost"
            onClick={() => write({ lookAgain: true })}
            title="Another search and a new note, about 15 cents of AI"
          >
            <UserSearch className="h-4 w-4" />
            Look for someone else
          </button>
        </div>
        <p className="ds-dim" style={{ fontSize: 12 }}>
          LinkedIn only lets free accounts add a note to a few connection requests a month. If you run out, connect
          without a note and send this once they accept. The app never sends anything on LinkedIn for you.
        </p>
      </div>
    );
  }

  return (
    <section id="message" ref={card} className="space-y-2" style={{ scrollMarginTop: 80 }}>
      <div className="flex items-baseline justify-between" style={{ gap: 12 }}>
        <h2 className="ds-h3">Next: message someone at {company}</h2>
        <span className="ds-dim" style={{ fontSize: 12 }}>From your own LinkedIn</span>
      </div>
      <div className="ds-card" style={{ padding: 16, borderColor: "var(--ds-line-strong)" }}>
        {update.isPending && note.status !== "sent" && (
          <Loader2 className="h-3.5 w-3.5 animate-spin ds-dim" style={{ float: "right" }} />
        )}
        {body}
      </div>
    </section>
  );
}
