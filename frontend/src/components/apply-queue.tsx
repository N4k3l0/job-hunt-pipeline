"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { CheckCircle2, ChevronDown, ChevronUp, Loader2, MessageSquare } from "lucide-react";
import { ApplicationWorkspace } from "@/components/application-workspace";
import { FillInFormButton } from "@/components/fill-in-form-button";
import { MessageStep } from "@/components/message-step";
import { SendForMe } from "@/components/send-for-me";
import type { AutoApplication } from "@/lib/types";

/** What an application is waiting on, in a few words. */
export function autoDetail(a: AutoApplication) {
  if (a.status === "needs_you" && a.prepared_by === "app") {
    return `Picked for you by the app. ${a.open_count} ${a.open_count === 1 ? "question needs" : "questions need"} you`;
  }
  if (a.status === "needs_you") return `${a.open_count} ${a.open_count === 1 ? "question needs" : "questions need"} you`;
  // A job the app waits to prepare says why, in plain words.
  if (a.status === "preparing") return a.error ?? "Reading the form and filling in your answers";
  if (a.status === "queued" && a.sending?.from_browser_only) {
    return "Their form emails you a code, so send this one from your browser.";
  }
  if (a.status === "queued") {
    // The last try didn't go through: say so where it can't be missed.
    if (a.error) return <span className="text-amber-500">{a.error}</span>;
    return "Everything's approved. Send it when you're ready.";
  }
  return a.error ?? "";
}

/** Sent today: the next step is a note to someone at the company. */
export interface SentToday {
  job_id: string;
  company: string | null;
  title: string | null;
  message: "drafted" | "sent" | "skipped" | null | undefined;
}

function Row({ open, onToggle, company, title, detail, actions, children, rowRef }: {
  open: boolean;
  onToggle?: () => void;
  company?: string | null;
  title?: string | null;
  detail?: React.ReactNode;
  actions?: React.ReactNode;
  children?: React.ReactNode;
  rowRef?: (el: HTMLDivElement | null) => void;
}) {
  return (
    <div
      ref={rowRef}
      className="ds-card"
      style={{ padding: 0, overflow: "hidden", scrollMarginTop: 80, borderColor: open ? "var(--ds-accent-edge)" : undefined }}
    >
      <div className="flex flex-wrap items-center" style={{ gap: 10, padding: "10px 14px" }}>
        <button
          type="button"
          onClick={onToggle}
          disabled={!onToggle}
          className="min-w-0 text-left"
          style={{ flex: "1 1 260px", background: "none", border: 0, padding: 0, color: "inherit", cursor: onToggle ? "pointer" : "default" }}
        >
          <div className="ds-muted truncate" style={{ fontSize: 12 }}>{company}</div>
          <div className="truncate" style={{ fontSize: 14, fontWeight: 500 }}>{title || "Unknown role"}</div>
          {detail && <div className="ds-dim" style={{ fontSize: 12, marginTop: 2 }}>{detail}</div>}
        </button>
        <div className="flex flex-wrap items-center" style={{ gap: 6 }}>
          {actions}
          {onToggle && (
            <button type="button" className="ds-btn ghost sm" onClick={onToggle} aria-label={open ? "Close" : "Open"}>
              {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </button>
          )}
        </div>
      </div>
      {open && children && (
        <div style={{ borderTop: "1px solid var(--ds-line)", padding: "14px 14px 16px", maxWidth: 880 }}>{children}</div>
      )}
    </div>
  );
}

function Group({ title, hint, count, children }: { title: string; hint?: string; count: number; children: React.ReactNode }) {
  if (!count) return null;
  return (
    <div className="space-y-2">
      <div className="flex items-baseline" style={{ gap: 8 }}>
        <h3 style={{ fontSize: 14, fontWeight: 600 }}>{title}</h3>
        <span className="ds-dim ds-mono" style={{ fontSize: 12 }}>{count}</span>
        {hint && <span className="ds-dim" style={{ fontSize: 12 }}>{hint}</span>}
      </div>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

/** Everything in progress, on one page: check and approve each
 *  application in place (the next one opens by itself), send the approved
 *  ones, and write to someone about the ones sent today. */
export function ApplyQueue({ applications, sentToday }: { applications: AutoApplication[]; sentToday: SentToday[] }) {
  const toCheck = applications.filter((a) => a.status === "needs_you");
  const toSend = applications.filter((a) => a.status === "queued" || a.status === "submitting");
  const preparing = applications.filter((a) => a.status === "preparing");
  const [openId, setOpenId] = useState<string | null>(null);
  const rows = useRef(new Map<string, HTMLDivElement>());

  const total = toCheck.length + toSend.length + preparing.length + sentToday.length;
  if (!total) return null;

  const toggle = (key: string) => setOpenId((current) => (current === key ? null : key));
  const keep = (key: string) => (el: HTMLDivElement | null) => {
    if (el) rows.current.set(key, el);
    else rows.current.delete(key);
  };
  // Approved: on to the next one that needs checking.
  const approvedFrom = (id: string) => () => {
    const after = toCheck.slice(toCheck.findIndex((a) => a.id === id) + 1).concat(toCheck);
    const next = after.find((a) => a.id !== id);
    setOpenId(next ? next.id : null);
    // Once it has opened, bring it into view.
    if (next) setTimeout(() => rows.current.get(next.id)?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
  };

  return (
    <section className="space-y-4">
      <div>
        <h2 className="ds-h3">Your queue</h2>
        <p className="ds-muted" style={{ fontSize: 13, marginTop: 4 }}>
          Check each one, approve it, and the next opens. Approved ones are ready to send from here.
        </p>
      </div>

      <Group title="To check" hint="Answer what needs you, then approve" count={toCheck.length}>
        {toCheck.map((a) => (
          <Row
            key={a.id}
            rowRef={keep(a.id)}
            open={openId === a.id}
            onToggle={() => toggle(a.id)}
            company={a.job?.company}
            title={a.job?.title}
            detail={autoDetail(a)}
            actions={
              openId === a.id ? null : (
                <button type="button" className="ds-btn primary sm" onClick={() => toggle(a.id)}>
                  Check and approve
                </button>
              )
            }
          >
            <ApplicationWorkspace id={a.id} inline onApproved={approvedFrom(a.id)} />
          </Row>
        ))}
      </Group>

      <Group title="Ready to send" hint="You press Submit on each form" count={toSend.length}>
        {toSend.map((a) => (
          <Row
            key={a.id}
            rowRef={keep(a.id)}
            open={openId === a.id}
            onToggle={() => toggle(a.id)}
            company={a.job?.company}
            title={a.job?.title}
            detail={autoDetail(a)}
            actions={
              a.sending?.from_browser_only && a.status === "queued" ? (
                openId === a.id ? null : (
                  <button type="button" className="ds-btn primary sm" onClick={() => toggle(a.id)}>
                    Send from your browser
                  </button>
                )
              ) : (
                <>
                  <SendForMe application={a} compact />
                  {!a.sending?.waiting && <FillInFormButton applicationId={a.id} onlyIfInstalled quiet />}
                </>
              )
            }
          >
            <ApplicationWorkspace id={a.id} inline />
          </Row>
        ))}
      </Group>

      <Group title="Being prepared" hint="About a minute each. They move to To check by themselves" count={preparing.length}>
        {preparing.map((a) => (
          <Row
            key={a.id}
            open={false}
            company={a.job?.company}
            title={a.job?.title}
            detail={autoDetail(a)}
            actions={<Loader2 className="h-4 w-4 animate-spin ds-dim" />}
          />
        ))}
      </Group>

      <Group title="Sent today" hint="Next: a short note to someone there" count={sentToday.length}>
        {sentToday.map((s) => {
          const key = `sent-${s.job_id}`;
          return (
            <Row
              key={key}
              rowRef={keep(key)}
              open={openId === key}
              onToggle={s.message === "skipped" ? undefined : () => toggle(key)}
              company={s.company}
              title={s.title}
              actions={
                s.message === "sent" ? (
                  <span className="ds-dim flex items-center" style={{ fontSize: 12, gap: 4 }}>
                    <CheckCircle2 className="h-3.5 w-3.5" /> Messaged
                  </span>
                ) : s.message === "skipped" ? (
                  <Link href={`/dashboard/jobs/${s.job_id}#message`} className="ds-dim" style={{ fontSize: 12 }}>
                    Skipped
                  </Link>
                ) : openId === key ? null : (
                  <button type="button" className="ds-btn sm" onClick={() => toggle(key)}>
                    <MessageSquare className="h-3.5 w-3.5" />
                    Message someone
                  </button>
                )
              }
            >
              <MessageStep jobId={s.job_id} />
            </Row>
          );
        })}
      </Group>
    </section>
  );
}
