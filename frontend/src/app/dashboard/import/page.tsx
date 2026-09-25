"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { OperationProgress } from "@/components/operation-progress";
import {
  Link as LinkIcon,
  MessageSquare,
  Loader2,
  CheckCircle2,
  ArrowRight,
  Bookmark,
  Copy,
  Check,
  Mail,
} from "lucide-react";
import {
  useImportJobUrl,
  useImportJobText,
  useImportBulkUrls,
} from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";

export default function ImportPage() {
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const toast = useToast();
  const router = useRouter();

  const importUrl = useImportJobUrl();
  const importText = useImportJobText();

  // Bookmarklet auto-import: when the user clicks the bookmarklet from
  // LinkedIn / Indeed / a company careers page, it opens this route
  // with the URL as a query param. We pre-fill, auto-submit, redirect
  // to the inbox on success. One click from anywhere on the web → job
  // in inbox. Ref-gate so it only ever runs once per tab.
  //
  // We read window.location.search directly instead of useSearchParams()
  // to avoid Next.js 16's static-export Suspense boundary requirement —
  // useSearchParams forces every parent up to a Suspense boundary,
  // which we don't want to add for one client-side query-string read.
  const autoRan = useRef(false);
  useEffect(() => {
    if (autoRan.current) return;
    if (typeof window === "undefined") return;
    const qsUrl = new URLSearchParams(window.location.search).get("url");
    if (!qsUrl) return;
    autoRan.current = true;
    setUrl(qsUrl);
    importUrl.mutate(qsUrl, {
      onSuccess: () => {
        toast.success("Job imported", {
          description: "Opening your inbox…",
        });
        // Tiny delay so the toast has a chance to render before navigation.
        setTimeout(() => router.replace("/dashboard/jobs"), 600);
      },
      onError: (err: any) =>
        toast.error("Import failed", { description: err?.message }),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleUrlImport(urlOverride?: string) {
    const target = (urlOverride ?? url).trim();
    if (!target) return;
    importUrl.mutate(target, {
      onSuccess: () => {
        setUrl("");
        toast.success("Job added", { description: "It's in your inbox." });
      },
      onError: (err: any) => toast.error("Import failed", { description: err?.message }),
    });
  }

  /**
   * One-click import from whatever URL is in the clipboard. Eliminates
   * the "paste + click Import" two-step the user just did, and dodges
   * the entire bookmarklet install dance (which most browsers make
   * user-hostile via javascript:-URL hardening).
   *
   * Clipboard API needs a user gesture — the button click counts —
   * so we read inside the click handler, not on mount.
   */
  async function handlePasteAndImport() {
    try {
      const clip = (await navigator.clipboard.readText()).trim();
      if (!clip) {
        toast.error("Clipboard is empty", {
          description: "Copy a job URL first, then click again.",
        });
        return;
      }
      if (!/^https?:\/\//i.test(clip)) {
        toast.error("Clipboard doesn't look like a URL", {
          description: "Make sure you copied the full link (it should start with http).",
        });
        return;
      }
      setUrl(clip);
      handleUrlImport(clip);
    } catch {
      toast.error("Couldn't read clipboard", {
        description: "Browser blocked it. Paste manually into the field instead.",
      });
    }
  }

  async function handleTextImport() {
    if (!text.trim()) return;
    importText.mutate(
      { text: text.trim(), source: "manual" },
      {
        onSuccess: () => {
          setText("");
          toast.success("Job added", { description: "It's in your inbox." });
        },
        onError: (err: any) => toast.error("Parse failed", { description: err?.message }),
      },
    );
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="font-display text-3xl font-semibold tracking-tight">Add a job</h1>
        <p className="text-muted-foreground">
          Found a job the app didn&apos;t? Add it with its link or its description, and it&apos;s scored like the rest.
        </p>
      </div>

      <Tabs defaultValue="url">
        <TabsList>
          <TabsTrigger value="url">
            <LinkIcon className="h-4 w-4 mr-1.5" />
            From a link
          </TabsTrigger>
          <TabsTrigger value="text">
            <MessageSquare className="h-4 w-4 mr-1.5" />
            From the description
          </TabsTrigger>
          <TabsTrigger value="email">
            <Mail className="h-4 w-4 mr-1.5" />
            From an email
          </TabsTrigger>
        </TabsList>

        <TabsContent value="url" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>From a link</CardTitle>
              <CardDescription>
                Copy the job&apos;s link, then press Paste and add. The app reads the page, scores the job for
                you and puts it in your inbox. It takes about 20 seconds.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* One-click flow: read whatever URL is in clipboard and
                  fire the import. Skips the paste-then-click two-step
                  AND skips the bookmarklet install entirely. */}
              <div className="rounded-xl border border-[var(--ds-accent-edge)] bg-[var(--ds-accent-soft)] p-4 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold">
                    Paste and add
                  </p>
                  <p className="text-xs text-muted-foreground mt-1 max-w-md leading-relaxed">
                    The quickest way: copy a job link from any site, then press this. No typing.
                  </p>
                </div>
                <Button
                  onClick={handlePasteAndImport}
                  disabled={importUrl.isPending}
                >
                  {importUrl.isPending ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Importing…
                    </>
                  ) : (
                    <>
                      <Copy className="h-4 w-4" />
                      Paste and add
                    </>
                  )}
                </Button>
              </div>

              <div className="relative">
                <div className="absolute inset-0 flex items-center">
                  <div className="w-full border-t border-white/[0.06]"></div>
                </div>
                <div className="relative flex justify-center text-xs">
                  <span className="bg-background px-2 text-muted-foreground/60">
                    or paste the link yourself
                  </span>
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="job-url">Job URL</Label>
                <div className="flex gap-2">
                  <Input
                    id="job-url"
                    value={url}
                    onChange={(e) => { setUrl(e.target.value); importUrl.reset(); }}
                    placeholder="https://careers.example.com/jobs/product-manager"
                    className="flex-1"
                    onKeyDown={(e) => e.key === "Enter" && handleUrlImport()}
                  />
                  <Button onClick={() => handleUrlImport()} disabled={importUrl.isPending || !url.trim()}>
                    {importUrl.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : importUrl.isSuccess ? (
                      <CheckCircle2 className="h-4 w-4" />
                    ) : (
                      <ArrowRight className="h-4 w-4" />
                    )}
                    {importUrl.isPending ? "Adding…" : importUrl.isSuccess ? "Added" : "Add"}
                  </Button>
                </div>
              </div>
              <OperationProgress
                active={importUrl.isPending}
                title="Adding this job"
                description="The app reads the page, finds the company's own application link, then scores the job against your profile."
                stages={[
                  { label: "Reading the page", durationMs: 5000, tip: "Loading the job's page." },
                  { label: "Parsing the posting", durationMs: 8000, tip: "Pulling out title, company, requirements, skills, salary, remote type." },
                  { label: "Finding the apply link", durationMs: 7000, tip: "Following job-board links to the company's own posting." },
                  { label: "Scoring it for you", durationMs: 3000, tip: "So it sits in the right place in your inbox." },
                ]}
              />
              {importUrl.isSuccess && (
                <div className="flex items-center gap-2 text-sm text-emerald-400">
                  <CheckCircle2 className="h-4 w-4" />
                  Job imported and added to your inbox.
                </div>
              )}
              {importUrl.isError && (
                <p className="text-sm text-destructive">{importUrl.error.message}</p>
              )}
              <p className="text-xs text-muted-foreground">
                Works with most job pages. If a page won&apos;t load, paste the job&apos;s description in the
                From the description tab instead.
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="text" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>From the description</CardTitle>
              <CardDescription>
                Paste the job description, or a message someone sent you about the job. The app pulls out the
                details.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="job-text">Job Description</Label>
                <textarea
                  id="job-text"
                  value={text}
                  onChange={(e) => { setText(e.target.value); importText.reset(); }}
                  className="flex min-h-[200px] w-full rounded-lg border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  placeholder={"Paste the job posting text here...\n\nExample:\nWe're hiring a Senior Marketing Manager to lead our growth team.\nLocation: London (Hybrid)\nSalary: £80k-£110k\nRequirements: 6+ years B2B SaaS marketing, demand-gen experience..."}
                />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">
                  Supports: job descriptions, WhatsApp forwards, recruiter messages
                </span>
                <Button onClick={handleTextImport} disabled={importText.isPending || !text.trim()}>
                  {importText.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : importText.isSuccess ? (
                    <CheckCircle2 className="h-4 w-4" />
                  ) : (
                    <ArrowRight className="h-4 w-4" />
                  )}
                  {importText.isPending ? "Reading…" : importText.isSuccess ? "Added" : "Add"}
                </Button>
              </div>
              <OperationProgress
                active={importText.isPending}
                title="Adding this job"
                description="The app pulls the details out of the text. If there's no apply link in it, the app looks one up so the Apply button works later."
                stages={[
                  { label: "Reading the text", durationMs: 6000, tip: "Pulling out title, company, requirements, skills, salary, remote type." },
                  { label: "Finding an apply link", durationMs: 5000, tip: "Looking the company up on common hiring systems." },
                  { label: "Scoring it for you", durationMs: 3000, tip: "So it sits in the right place in your inbox." },
                ]}
              />
              {importText.isSuccess && (
                <div className="flex items-center gap-2 text-sm text-emerald-400">
                  <CheckCircle2 className="h-4 w-4" />
                  Job imported and added to your inbox.
                </div>
              )}
              {importText.isError && (
                <p className="text-sm text-destructive">{importText.error.message}</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="email" className="mt-4">
          <EmailBulkImportPanel />
        </TabsContent>
      </Tabs>

      {/* Bookmarklet — installs once, then any LinkedIn / Indeed /
          company careers page is one-click importable from the
          browser bar. Built with origin from window so it works in
          local dev AND prod without manual edits. */}
      <BookmarkletCard />
    </div>
  );
}


function BookmarkletCard() {
  // Build the bookmarklet at runtime so it points at whatever origin
  // the user is on (localhost in dev, the Vercel URL in prod). The
  // `auto=1` flag tells the import page to fire immediately.
  const [origin, setOrigin] = useState("");
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (typeof window !== "undefined") setOrigin(window.location.origin);
  }, []);

  const bookmarkletHref = origin
    ? `javascript:(function(){var u=encodeURIComponent(location.href);window.open('${origin}/dashboard/import?url='+u+'&auto=1','_blank');})();`
    : "javascript:void(0);";

  const handleCopy = () => {
    navigator.clipboard.writeText(bookmarkletHref).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    });
  };

  return (
    <Card className="border-white/[0.06]">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Bookmark className="h-4 w-4 text-muted-foreground" />
          <span>Optional: browser bookmark shortcut</span>
          <Badge variant="outline" className="ml-1 text-[10px] uppercase tracking-wider">
            Advanced
          </Badge>
        </CardTitle>
        <CardDescription>
          For power users: skip the &quot;come back to this page&quot; step
          entirely. Install once, then click a bookmark on any job page
          to import it without switching tabs. Setup is a few clicks
          (browsers make this fiddly). It&apos;s fine to skip it and use Paste and add above.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <details className="space-y-5">
          <summary className="cursor-pointer text-sm text-foreground hover:text-[var(--ds-accent)]">
            Show install steps
          </summary>
          <div className="mt-4 space-y-5">
        {/* Step 1: copy the bookmarklet URL */}
        <div className="space-y-2">
          <p className="text-sm font-medium flex items-center gap-2">
            <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-[var(--ds-accent-soft)] text-[var(--ds-accent)] text-xs font-bold">1</span>
            Copy this URL
          </p>
          <div className="flex flex-wrap items-center gap-2 pl-7">
            <Button
              variant="outline"
              size="sm"
              onClick={handleCopy}
              disabled={!origin}
                          >
              {copied ? (
                <>
                  <Check className="h-3.5 w-3.5 text-emerald-400" />
                  Copied. Now paste it in step 3
                </>
              ) : (
                <>
                  <Copy className="h-3.5 w-3.5" />
                  Copy bookmarklet URL
                </>
              )}
            </Button>
          </div>
        </div>

        {/* Step 2: right-click bookmarks bar */}
        <div className="space-y-2">
          <p className="text-sm font-medium flex items-center gap-2">
            <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-[var(--ds-accent-soft)] text-[var(--ds-accent)] text-xs font-bold">2</span>
            Right-click the bookmarks bar
          </p>
          <div className="pl-7 space-y-2 text-sm text-muted-foreground leading-relaxed">
            <p>
              If the bookmarks bar isn&apos;t visible, show it first:{" "}
              <kbd className="px-1.5 py-0.5 rounded border border-white/10 bg-white/[0.04] text-xs">⌘⇧B</kbd> (Mac)
              {" "}/{" "}
              <kbd className="px-1.5 py-0.5 rounded border border-white/10 bg-white/[0.04] text-xs">Ctrl+Shift+B</kbd> (Windows / Linux).
              Then <span className="text-foreground">right-click in any empty area of the bookmarks bar</span>:
              the empty space to the right of your existing bookmarks, NOT on an existing bookmark.
            </p>
            <p>
              Choose <code className="px-1.5 py-0.5 rounded bg-white/[0.04] text-xs text-foreground">Add page…</code> (Chrome / Brave / Edge),
              {" "}<code className="px-1.5 py-0.5 rounded bg-white/[0.04] text-xs text-foreground">New Bookmark…</code> (Firefox),
              or use the Bookmarks menu → <code className="px-1.5 py-0.5 rounded bg-white/[0.04] text-xs text-foreground">Edit Bookmarks</code> → <code className="px-1.5 py-0.5 rounded bg-white/[0.04] text-xs text-foreground">+</code> (Safari).
            </p>
            <p className="text-xs italic">
              ⚠ The <kbd className="px-1 py-0.5 rounded border border-white/10 bg-white/[0.04] text-[10px]">⌘D</kbd> /{" "}
              <kbd className="px-1 py-0.5 rounded border border-white/10 bg-white/[0.04] text-[10px]">Ctrl+D</kbd> shortcut won&apos;t
              work: that dialog only shows Name and Folder, not the URL. Use the right-click path above.
            </p>
          </div>
        </div>

        {/* Step 3: fill the dialog */}
        <div className="space-y-2">
          <p className="text-sm font-medium flex items-center gap-2">
            <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-[var(--ds-accent-soft)] text-[var(--ds-accent)] text-xs font-bold">3</span>
            Fill in the bookmark
          </p>
          <div className="pl-7 space-y-2 text-sm text-muted-foreground leading-relaxed">
            <p>The dialog that opens has BOTH Name and URL fields. Fill them in:</p>
            <ul className="space-y-1 pl-5 list-disc">
              <li>
                <span className="text-foreground">Name</span>:{" "}
                <code className="px-1.5 py-0.5 rounded bg-white/[0.04] text-xs text-foreground">Save to JobHunt</code>
              </li>
              <li>
                <span className="text-foreground">URL</span>: paste the URL you copied in step 1{" "}
                (<kbd className="px-1.5 py-0.5 rounded border border-white/10 bg-white/[0.04] text-xs">⌘ V</kbd>
                {" "}/{" "}
                <kbd className="px-1.5 py-0.5 rounded border border-white/10 bg-white/[0.04] text-xs">Ctrl V</kbd>)
                {". "}It must start with{" "}
                <code className="px-1.5 py-0.5 rounded bg-white/[0.04] text-xs text-foreground">javascript:</code>
              </li>
              <li>Save / Done</li>
            </ul>
          </div>
        </div>

        {/* Step 4: use it */}
        <div className="space-y-2">
          <p className="text-sm font-medium flex items-center gap-2">
            <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-400 text-xs font-bold">4</span>
            Use it
          </p>
          <p className="text-sm text-muted-foreground pl-7 leading-relaxed">
            On any job page, click{" "}
            <span className="text-foreground font-medium">Save to JobHunt</span> in your
            bookmarks bar. The job opens in a new tab and lands in your inbox in about 20 seconds.
          </p>
        </div>

        <details className="text-xs text-muted-foreground border-t border-white/[0.04] pt-3">
          <summary className="cursor-pointer hover:text-foreground">
            Troubleshooting
          </summary>
          <ul className="mt-2 space-y-1.5 pl-4 list-disc">
            <li>
              <span className="text-foreground">Bookmark menu missing the URL field?</span>{" "}
              Open the full bookmarks manager (<kbd className="px-1 py-0.5 rounded border border-white/10 bg-white/[0.04] text-[10px]">⌘⇧B</kbd> / <kbd className="px-1 py-0.5 rounded border border-white/10 bg-white/[0.04] text-[10px]">Ctrl⇧O</kbd>),
              find the new bookmark, right-click → Edit, and replace the URL there.
            </li>
            <li>
              <span className="text-foreground">Clicking the bookmark doesn&apos;t open this app?</span>{" "}
              Your browser stripped <code>javascript:</code> from the saved URL on paste.
              Re-copy, re-paste, and check the URL field still starts with{" "}
              <code className="text-foreground">javascript:</code> before saving.
            </li>
            <li>
              <span className="text-foreground">Imported job didn&apos;t land in the inbox?</span>{" "}
              You need to be logged into this dashboard in the same browser: the
              session cookies are how we authenticate the import. Log in, then
              click the bookmarklet again.
            </li>
            <li>
              <span className="text-foreground">What happens after I click it?</span>{" "}
              The bookmarklet reads the URL of the current tab, opens a new tab
              here pre-loaded with that URL, auto-fires the import (parse +
              apply-link resolve + scoring), and redirects you to your inbox.
            </li>
          </ul>
        </details>
          </div>
        </details>
      </CardContent>
    </Card>
  );
}


/**
 * Bulk-import job URLs from a pasted email body (or any text).
 *
 * Designed for LinkedIn job-alert digests — those typically contain
 * 10–30 URLs and are a pain to import one at a time. User receives
 * the email normally, copies the body, pastes here, clicks import.
 * Backend extracts every job-posting URL (regex against known hosts),
 * processes 8 per call, and tells the frontend whether there are more
 * to chain.
 *
 * No Postmark / DNS / inbound-email infrastructure needed — way
 * simpler than building real email forwarding for v1.
 */
function EmailBulkImportPanel() {
  const importBulk = useImportBulkUrls();
  const [emailText, setEmailText] = useState("");
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);
  const [stats, setStats] = useState<{
    found: number; imported: number; failed: number;
  } | null>(null);
  const [results, setResults] = useState<{ url: string; status: "ok" | "failed"; error?: string }[]>([]);

  const handleRun = async () => {
    if (!emailText.trim()) return;
    setRunning(true);
    setDone(false);
    setStats({ found: 0, imported: 0, failed: 0 });
    setResults([]);

    let remaining = emailText.trim();
    let safetyCap = 10; // 10 batches × 8 = 80 URLs/run, more than enough for any digest
    while (safetyCap-- > 0) {
      try {
        const batch = await importBulk.mutateAsync({ text: remaining });
        setStats((prev) => ({
          found: Math.max(prev?.found ?? 0, batch.found),
          imported: (prev?.imported ?? 0) + batch.imported,
          failed: (prev?.failed ?? 0) + batch.failed,
        }));
        setResults((prev) => [...prev, ...batch.results]);
        if (!batch.has_more || batch.processed === 0) break;
        // Next batch sees only the still-unprocessed URLs
        remaining = batch.remaining_urls.join("\n");
      } catch {
        break;
      }
    }
    setRunning(false);
    setDone(true);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>From an email</CardTitle>
        <CardDescription>
          Paste a job alert email, or any text with job links in it. The app adds every job it finds,
          from any job board or company careers page.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="email-body">Email body</Label>
          <textarea
            id="email-body"
            value={emailText}
            onChange={(e) => setEmailText(e.target.value)}
            placeholder={
              "Paste the whole email here.\n\nA LinkedIn job alert works well:\nselect everything in the email,\ncopy it, then paste it in this box."
            }
            spellCheck
            className="block w-full min-h-[260px] resize-y rounded-lg bg-white/[0.02] border border-white/[0.04] focus:border-[var(--ds-accent-edge)] focus:outline-none p-3 text-sm leading-relaxed font-sans whitespace-pre-line transition-colors"
          />
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={handleRun} disabled={running || !emailText.trim()}>
            {running ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Adding the jobs…
              </>
            ) : (
              <>
                <ArrowRight className="h-4 w-4" />
                {done ? "Run again" : "Add the jobs"}
              </>
            )}
          </Button>
          {stats && (running || done) && (
            <Badge variant="outline" className="font-mono text-xs">
              Found {stats.found} · Added {stats.imported}
              {stats.failed > 0 ? ` · Failed ${stats.failed}` : ""}
            </Badge>
          )}
        </div>

        {results.length > 0 && (
          <details className="text-xs text-muted-foreground" open>
            <summary className="cursor-pointer hover:text-foreground">
              What happened to each link ({results.length})
            </summary>
            <ul className="mt-2 space-y-1.5 max-h-[260px] overflow-y-auto">
              {results.map((r, i) => (
                <li key={i} className="flex items-start gap-2 leading-relaxed">
                  {r.status === "ok" ? (
                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 shrink-0 mt-0.5" />
                  ) : (
                    <span className="h-3.5 w-3.5 rounded-full bg-destructive/30 shrink-0 mt-0.5" />
                  )}
                  <span className="flex-1 min-w-0 break-words font-mono">
                    {r.url.length > 90 ? r.url.slice(0, 87) + "…" : r.url}
                    {r.error && (
                      <span className="block text-destructive/80 mt-0.5">
                        {r.error}
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </details>
        )}

        <div className="rounded-lg border border-white/[0.04] bg-white/[0.01] p-3 text-xs text-muted-foreground space-y-1.5">
          <p className="text-foreground font-medium">Setup: LinkedIn job alerts</p>
          <p>
            On LinkedIn, open a search you care about, press Set alert and choose Daily. LinkedIn emails you
            every morning. Copy that email and paste it here, and the app adds every job in it.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
