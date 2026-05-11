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
import {
  Link as LinkIcon,
  MessageSquare,
  Loader2,
  CheckCircle2,
  ArrowRight,
  Bookmark,
  Copy,
  Check,
} from "lucide-react";
import { useImportJobUrl, useImportJobText } from "@/hooks/use-api";
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

  async function handleUrlImport() {
    if (!url.trim()) return;
    importUrl.mutate(url.trim(), {
      onSuccess: () => {
        setUrl("");
        toast.success("Job imported", { description: "It's in your inbox — go check." });
      },
      onError: (err: any) => toast.error("Import failed", { description: err?.message }),
    });
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
        </TabsList>

        <TabsContent value="url" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Import from URL</CardTitle>
              <CardDescription>
                Paste a job posting URL from any site. We'll extract the details
                automatically using Firecrawl + AI.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
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
                  <Button onClick={handleUrlImport} disabled={importUrl.isPending || !url.trim()}>
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
    <Card className="border-amber-500/15">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Bookmark className="h-5 w-5 text-amber-400" />
          One-click import from anywhere
        </CardTitle>
        <CardDescription>
          Install once, then click the bookmark while on any LinkedIn /
          Indeed / company careers page — that job lands in your inbox,
          no copy-paste. Most modern browsers block drag-to-bookmark for
          JavaScript shortcuts (security hardening), so the reliable
          install path is the manual one below.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
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
      </CardContent>
    </Card>
  );
}
