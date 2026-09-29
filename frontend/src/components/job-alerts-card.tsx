"use client";

import { useState } from "react";
import { Check, Copy, ExternalLink, Loader2, Mail } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { API_BASE } from "@/lib/api-client";
import { buildLinkedInAlertScript } from "@/lib/linkedin-alert-script";
import {
  useCreateJobAlertKey, useCurrentUser, useDeleteJobAlertKey, useJobAlertForwarding, useJobAlertStatus,
} from "@/hooks/use-api";

function timeAgo(iso: string | null) {
  if (!iso) return null;
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

const SCRIPT_STEPS = [
  <>
    Open{" "}
    <a href="https://script.google.com/home/projects/create" target="_blank" rel="noopener noreferrer" className="underline">
      a new Google Apps Script project <ExternalLink className="inline h-3 w-3" />
    </a>{" "}
    while signed in to the Gmail account that gets your LinkedIn job alerts.
  </>,
  <>Delete the sample code, paste the script, and save (⌘S or Ctrl+S).</>,
  <>
    Pick <code className="text-foreground">setUp</code> in the menu next to <strong>Run</strong>, then press Run.
  </>,
  <>
    Google asks for permission. Choose your account, then <strong>Advanced</strong> →{" "}
    <strong>Go to Untitled project (unsafe)</strong> → <strong>Allow</strong>. Google shows this warning for any
    script it hasn&apos;t reviewed; this one is yours and runs only in your account.
  </>,
  <>That&apos;s it. It checks for new alerts every 10 minutes, and what it sends shows up here.</>,
];

function CopyButton({ text, label }: { text: string; label: string }) {
  const toast = useToast();
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      toast.error("Couldn't copy", { description: "Select it and copy it yourself." });
    }
  }
  return (
    <Button size="sm" onClick={copy}>
      {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
      {copied ? "Copied" : label}
    </Button>
  );
}

/** Forward LinkedIn alerts to the app's shared inbox: a Gmail setting, no code. */
function ForwardingSteps({ address, code }: { address: string; code: string | null }) {
  return (
    <div className="space-y-3 text-sm">
      <p>
        Forward your LinkedIn job alerts to your own address below. You set it up once in Gmail, and new alerts then
        come here by themselves.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <code className="rounded-md border px-2.5 py-1.5 text-sm text-foreground" style={{ borderColor: "var(--ds-line-strong)" }}>
          {address}
        </code>
        <CopyButton text={address} label="Copy address" />
      </div>
      <ol className="list-decimal space-y-1.5 pl-5 text-muted-foreground">
        <li>
          In Gmail, open <strong>Settings</strong> (the gear, top right) → <strong>See all settings</strong> →{" "}
          <strong>Forwarding and POP/IMAP</strong>.
        </li>
        <li>
          Press <strong>Add a forwarding address</strong>, paste your address, then <strong>Next</strong> →{" "}
          <strong>Proceed</strong> → <strong>OK</strong>.
        </li>
        <li>
          Gmail sends a code to check. It shows up here within about 10 minutes:{" "}
          {code ? (
            <strong className="text-foreground">{code}</strong>
          ) : (
            <span className="inline-flex items-center gap-1">
              <Loader2 className="h-3 w-3 animate-spin" /> waiting for Gmail&apos;s code
            </span>
          )}
          . Type it next to <strong>Verify</strong> in Gmail and press Verify. Leave <strong>Disable forwarding</strong>{" "}
          selected, so the rest of your email stays yours.
        </li>
        <li>
          In Gmail&apos;s search bar, type <code className="text-foreground">from:jobalerts-noreply@linkedin.com</code>, press
          the options button at the right end of the search bar, then <strong>Create filter</strong>. Tick{" "}
          <strong>Forward it to</strong>, choose your address, and press <strong>Create filter</strong>.
        </li>
      </ol>
      <p className="text-xs text-muted-foreground">
        Not on Gmail? Most email services have a forwarding rule: send email from jobalerts-noreply@linkedin.com to the
        address above. Your alerts pass through the app&apos;s shared inbox, which the app&apos;s admin can see. Only the
        job alerts do, nothing else.
      </p>
    </div>
  );
}

export function JobAlertsCard() {
  const toast = useToast();
  const { data: me } = useCurrentUser();
  const { data: status, isLoading } = useJobAlertStatus();
  const waiting = !status?.has_key && !status?.emails_read;
  const { data: forwarding } = useJobAlertForwarding(waiting);
  const createKey = useCreateJobAlertKey();
  const deleteKey = useDeleteJobAlertKey();
  // Only known right after it's created: the backend stores a hash.
  const [script, setScript] = useState<string | null>(null);
  const [scriptWay, setScriptWay] = useState(false);

  const create = () =>
    createKey.mutate(undefined, {
      onSuccess: ({ key }) => setScript(buildLinkedInAlertScript(API_BASE, key)),
      onError: (e) => toast.error("Couldn't create a key", { description: e instanceof Error ? e.message : undefined }),
    });

  const stop = () =>
    deleteKey.mutate(undefined, {
      onSuccess: () => {
        setScript(null);
        toast.success("LinkedIn alert sync stopped", {
          description: "You can also delete the Apps Script project in your Google account.",
        });
      },
    });

  const isAdmin = me?.role === "admin";
  // Everyone but the inbox's own admin forwards, once an admin's script
  // reads a shared inbox; a user with their own script doesn't need to.
  const forwards = !!forwarding?.ready && !forwarding.inbox_owner && !status?.has_key && !scriptWay;
  const lastSync = timeAgo(status?.last_used_at ?? status?.last_email_at ?? null);
  const hasSynced = (status?.emails_read ?? 0) > 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Mail className="h-5 w-5" />
          LinkedIn job alerts
        </CardTitle>
        <CardDescription>
          Add the jobs from your LinkedIn job alert emails to your dashboard. Jobs LinkedIn sends you are marked, and
          Rate matches shows how often they fit.
          {isAdmin && !forwarding?.ready && (
            <>
              {" "}
              Set this up in the Gmail that gets your alerts, and it also becomes the inbox your users forward their
              alerts to.
            </>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading ? (
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        ) : (
          <>
            {(status?.has_key || hasSynced) && !script && (
              <div className="space-y-2 text-sm">
                <div>
                  {hasSynced ? (
                    <>
                      Last alert <strong>{lastSync}</strong>: {status!.emails_read}{" "}
                      {status!.emails_read === 1 ? "email" : "emails"} read, {status!.jobs_sent}{" "}
                      {status!.jobs_sent === 1 ? "job" : "jobs"} sent to you.
                    </>
                  ) : (
                    <>Key created. Waiting for the script&apos;s first sync.</>
                  )}
                </div>
                {status!.searches.length > 0 && (
                  <div className="text-muted-foreground">
                    Alerts:{" "}
                    {status!.searches
                      .map((s) => `${s.search}${s.location ? ` in ${s.location}` : ""} (${s.jobs})`)
                      .join(", ")}
                  </div>
                )}
                {forwarding?.ready && forwarding.inbox_owner && (
                  <div className="text-muted-foreground">
                    Your users forward their alerts here too. Each sees their own address on this page.
                  </div>
                )}
              </div>
            )}

            {forwards && !hasSynced && forwarding?.address && (
              <ForwardingSteps address={forwarding.address} code={forwarding.confirmation?.code ?? null} />
            )}

            {script ? (
              <div className="space-y-3">
                <ol className="list-decimal space-y-1.5 pl-5 text-sm text-muted-foreground">
                  {SCRIPT_STEPS.map((step, i) => <li key={i}>{step}</li>)}
                </ol>
                <div className="flex items-center gap-2">
                  <CopyButton text={script} label="Copy script" />
                  <span className="text-xs text-muted-foreground">
                    It contains your key. Don&apos;t share it; you can replace the key here any time.
                  </span>
                </div>
                <textarea
                  readOnly
                  value={script}
                  onFocus={(e) => e.currentTarget.select()}
                  className="block h-48 w-full resize-y rounded-lg border border-white/[0.06] bg-white/[0.02] p-3 font-mono text-xs"
                />
              </div>
            ) : forwards ? (
              <button type="button" className="text-xs text-muted-foreground underline" onClick={() => setScriptWay(true)}>
                Or run a small script in your own Gmail instead
              </button>
            ) : (
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" onClick={create} disabled={createKey.isPending}>
                  {createKey.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                  {status?.has_key ? "Get a new script" : "Set up LinkedIn alerts"}
                </Button>
                {status?.has_key && (
                  <>
                    <Button size="sm" variant="outline" onClick={stop} disabled={deleteKey.isPending}>
                      Stop syncing
                    </Button>
                    <span className="text-xs text-muted-foreground">
                      A new script replaces your key, so paste it over the old one.
                    </span>
                  </>
                )}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
