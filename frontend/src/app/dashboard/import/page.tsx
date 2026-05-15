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
        toast.success("Job imported", { description: "It's in your inbox — go check." });
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
    } catch (e: any) {
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
          toast.success("Job imported", { description: "It's in your inbox — go check." });
        },
        onError: (err: any) => toast.error("Parse failed", { description: err?.message }),
      },
    );
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="font-display text-3xl font-semibold tracking-tight">Import Job</h1>
        <p className="text-muted-foreground">
          Add a job manually by URL or by pasting the description
        </p>
      </div>

      <Tabs defaultValue="url">
        <TabsList>
          <TabsTrigger value="url">
            <LinkIcon className="h-4 w-4 mr-1.5" />
            By URL
          </TabsTrigger>
          <TabsTrigger value="text">
            <MessageSquare className="h-4 w-4 mr-1.5" />
            By Text
          </TabsTrigger>
          <TabsTrigger value="email">
            <Mail className="h-4 w-4 mr-1.5" />
            From email
          </TabsTrigger>
        </TabsList>

        <TabsContent value="url" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Import from URL</CardTitle>
              <CardDescription>
                Copy any job URL → click the amber button below. That&apos;s it.
                We parse + score + drop it in your inbox in ~15–25 seconds.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* One-click flow: read whatever URL is in clipboard and
                  fire the import. Skips the paste-then-click two-step
                  AND skips the bookmarklet install entirely. */}
              <div className="rounded-xl border border-amber-500/30 bg-amber-500/[0.06] p-4 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-amber-200">
                    Paste & import
                  </p>
                  <p className="text-xs text-muted-foreground mt-1 max-w-md leading-relaxed">
                    Easiest path. Copy a job URL on LinkedIn / Indeed /
                    anywhere, then click. No typing, no bookmarklet.
                  </p>
                </div>
                <Button
                  onClick={handlePasteAndImport}
                  disabled={importUrl.isPending}
                  className="bg-amber-500 hover:bg-amber-400 text-black font-semibold"
                >
                  {importUrl.isPending ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Importing…
                    </>
                  ) : (
                    <>
                      <Copy className="h-4 w-4" />
                      Paste & import
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
                    or paste manually
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
                    {importUrl.isPending ? "Importing..." : importUrl.isSuccess ? "Queued!" : "Import"}
                  </Button>
                </div>
              </div>
              <OperationProgress
                active={importUrl.isPending}
                title="Importing this job"
                description="Firecrawl scrapes the page, Claude parses it into structured fields, we resolve the direct apply link, then score it against your profile."
                stages={[
                  { label: "Fetching the page", durationMs: 5000, tip: "Firecrawl renders the URL — handles JS-heavy ATS pages that plain HTTP can't read." },
                  { label: "Parsing with Claude", durationMs: 8000, tip: "Pulling out title, company, requirements, skills, salary, remote type." },
                  { label: "Resolving the apply link", durationMs: 7000, tip: "Going through aggregator redirects to find the direct posting URL." },
                  { label: "Scoring + adding to inbox", durationMs: 3000, tip: "Computing your fit so the inbox sort is meaningful right away." },
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
              <div className="flex flex-wrap gap-2">
                <span className="text-xs text-muted-foreground">Works with:</span>
                {["LinkedIn", "Indeed", "Greenhouse", "Lever", "Workday", "Any career page"].map(
                  (site) => (
                    <Badge key={site} variant="outline" className="text-xs font-normal">
                      {site}
                    </Badge>
                  )
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="text" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Import from Text</CardTitle>
              <CardDescription>
                Paste a job description or WhatsApp message. AI will extract the details.
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
                  placeholder={"Paste the job posting text here...\n\nExample:\nWe're hiring a Senior Product Manager for our AI Platform team.\nLocation: San Francisco (Hybrid)\nSalary: $180k-$240k\nRequirements: 5+ years PM experience, AI/ML background..."}
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
                  {importText.isPending ? "Processing..." : importText.isSuccess ? "Queued!" : "Import"}
                </Button>
              </div>
              <OperationProgress
                active={importText.isPending}
                title="Importing this job"
                description="Claude parses the text into structured fields. If you didn't paste an apply URL, we also resolve one for you so the Apply button works instantly later."
                stages={[
                  { label: "Reading the text with Claude", durationMs: 6000, tip: "Pulling out title, company, requirements, skills, salary, remote type." },
                  { label: "Resolving an apply link", durationMs: 5000, tip: "Looking up the company on Greenhouse / Lever / Ashby, plus a Claude web_search if needed." },
                  { label: "Scoring + adding to inbox", durationMs: 3000, tip: "Computing your fit so the inbox sort is meaningful right away." },
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
          (browsers make bookmarklet install user-hostile lately) —
          fine to skip and just use Paste & import above.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <details className="space-y-5">
          <summary className="cursor-pointer text-sm text-foreground hover:text-amber-300">
            Show install steps
          </summary>
          <div className="mt-4 space-y-5">
        {/* Step 1: copy the bookmarklet URL */}
        <div className="space-y-2">
          <p className="text-sm font-medium flex items-center gap-2">
            <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-amber-500/15 text-amber-400 text-xs font-bold">1</span>
            Copy this URL
          </p>
          <div className="flex flex-wrap items-center gap-2 pl-7">
            <Button
              variant="outline"
              size="sm"
              onClick={handleCopy}
              disabled={!origin}
              className="bg-amber-500/10 border-amber-500/40 text-amber-300 hover:bg-amber-500/15"
            >
              {copied ? (
                <>
                  <Check className="h-3.5 w-3.5 text-emerald-400" />
                  Copied — now paste it in step 3
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
            <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-amber-500/15 text-amber-400 text-xs font-bold">2</span>
            Right-click the bookmarks bar
          </p>
          <div className="pl-7 space-y-2 text-sm text-muted-foreground leading-relaxed">
            <p>
              If the bookmarks bar isn&apos;t visible, show it first:{" "}
              <kbd className="px-1.5 py-0.5 rounded border border-white/10 bg-white/[0.04] text-xs">⌘⇧B</kbd> (Mac)
              {" "}/{" "}
              <kbd className="px-1.5 py-0.5 rounded border border-white/10 bg-white/[0.04] text-xs">Ctrl+Shift+B</kbd> (Windows / Linux).
              Then <span className="text-foreground">right-click in any empty area of the bookmarks bar</span> —
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
              work — that dialog only shows Name + Folder, not URL. Use the right-click path above.
            </p>
          </div>
        </div>

        {/* Step 3: fill the dialog */}
        <div className="space-y-2">
          <p className="text-sm font-medium flex items-center gap-2">
            <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-amber-500/15 text-amber-400 text-xs font-bold">3</span>
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
                {" "}— must start with{" "}
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
            Browse any LinkedIn / Indeed / company careers page → click{" "}
            <span className="text-foreground font-medium">Save to JobHunt</span> in your
            bookmarks bar → the job opens in a new tab and lands in your inbox
            within ~15–25 seconds.
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
              You need to be logged into this dashboard in the same browser — the
              session cookies are how we authenticate the import. Log in, then
              click the bookmarklet again.
            </li>
            <li>
              <span className="text-foreground">What happens after I click it?</span>{" "}
              The bookmarklet reads the URL of the current tab, opens a new tab
              here pre-loaded with that URL, auto-fires the import (Claude parse +
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
        <CardTitle>Import from email body</CardTitle>
        <CardDescription>
          Paste a LinkedIn job-alert email (or any text with job URLs).
          We pull every posting link out, ingest each, and drop them in
          your inbox. Recognises LinkedIn, Greenhouse, Lever, Ashby,
          Workable, Indeed, Wellfound, SmartRecruiters, Workday, and
          common ATSes.
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
              "Paste the whole email body here.\n\nLinkedIn's daily job alert\nworks great — just Cmd+A,\nCmd+C in the email, then\npaste in this box."
            }
            spellCheck
            className="block w-full min-h-[260px] resize-y rounded-lg bg-white/[0.02] border border-white/[0.04] focus:border-amber-500/30 focus:outline-none p-3 text-sm leading-relaxed font-sans whitespace-pre-line transition-colors"
          />
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={handleRun} disabled={running || !emailText.trim()}>
            {running ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Extracting + importing…
              </>
            ) : (
              <>
                <ArrowRight className="h-4 w-4" />
                {done ? "Run again" : "Extract & import"}
              </>
            )}
          </Button>
          {stats && (running || done) && (
            <Badge variant="outline" className="font-mono text-xs">
              Found {stats.found} · Imported {stats.imported}
              {stats.failed > 0 ? ` · Failed ${stats.failed}` : ""}
            </Badge>
          )}
        </div>

        {results.length > 0 && (
          <details className="text-xs text-muted-foreground" open>
            <summary className="cursor-pointer hover:text-foreground">
              Per-URL outcomes ({results.length})
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
            On LinkedIn: go to a search you care about → Set alert → choose Daily. LinkedIn
            emails you every morning. Forward (or just copy/paste) the email
            body here and we&apos;ll import every posting in it.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
