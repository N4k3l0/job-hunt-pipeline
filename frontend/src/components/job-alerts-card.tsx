"use client";

import { useState } from "react";
import { Check, Copy, ExternalLink, Loader2, Mail } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { API_BASE } from "@/lib/api-client";
import { buildLinkedInAlertScript } from "@/lib/linkedin-alert-script";
import { useCreateJobAlertKey, useDeleteJobAlertKey, useJobAlertStatus } from "@/hooks/use-api";

function timeAgo(iso: string | null) {
  if (!iso) return null;
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

const STEPS = [
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
  <>That&apos;s it. It checks for new alerts every hour, and what it sends shows up here.</>,
];

export function JobAlertsCard() {
  const toast = useToast();
  const { data: status, isLoading } = useJobAlertStatus();
  const createKey = useCreateJobAlertKey();
  const deleteKey = useDeleteJobAlertKey();
  // Only known right after it's created: the backend stores a hash.
  const [script, setScript] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const create = () =>
    createKey.mutate(undefined, {
      onSuccess: ({ key }) => {
        setScript(buildLinkedInAlertScript(API_BASE, key));
        setCopied(false);
      },
      onError: (e) => toast.error("Couldn't create a key", { description: e instanceof Error ? e.message : undefined }),
    });

  const copy = async () => {
    if (!script) return;
    try {
      await navigator.clipboard.writeText(script);
      setCopied(true);
    } catch {
      toast.error("Couldn't copy", { description: "Select the script and copy it yourself." });
    }
  };

  const stop = () =>
    deleteKey.mutate(undefined, {
      onSuccess: () => {
        setScript(null);
        toast.success("LinkedIn alert sync stopped", {
          description: "You can also delete the Apps Script project in your Google account.",
        });
      },
    });

  const lastSync = timeAgo(status?.last_used_at ?? null);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Mail className="h-5 w-5" />
          LinkedIn job alerts
        </CardTitle>
        <CardDescription>
          Add the jobs from your LinkedIn job alert emails to your dashboard. A small script in your own Gmail sends
          only those emails, every hour. Jobs LinkedIn sends you are marked, and Rate matches shows how often they
          fit.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading ? (
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        ) : (
          <>
            {status?.has_key && !script && (
              <div className="space-y-2 text-sm">
                <div>
                  {lastSync ? (
                    <>
                      Last sync <strong>{lastSync}</strong>: {status.emails_read}{" "}
                      {status.emails_read === 1 ? "email" : "emails"} read, {status.jobs_sent}{" "}
                      {status.jobs_sent === 1 ? "job" : "jobs"} sent to you.
                    </>
                  ) : (
                    <>Key created. Waiting for the script&apos;s first sync.</>
                  )}
                </div>
                {status.searches.length > 0 && (
                  <div className="text-muted-foreground">
                    Alerts:{" "}
                    {status.searches
                      .map((s) => `${s.search}${s.location ? ` in ${s.location}` : ""} (${s.jobs})`)
                      .join(", ")}
                  </div>
                )}
              </div>
            )}

            {script ? (
              <div className="space-y-3">
                <ol className="list-decimal space-y-1.5 pl-5 text-sm text-muted-foreground">
                  {STEPS.map((step, i) => <li key={i}>{step}</li>)}
                </ol>
                <div className="flex items-center gap-2">
                  <Button size="sm" onClick={copy}>
                    {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                    {copied ? "Copied" : "Copy script"}
                  </Button>
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
