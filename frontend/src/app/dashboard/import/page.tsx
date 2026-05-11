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
  // `auto=1` flag tells the import page to fire immediately instead
  // of just pre-filling the input.
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
      setTimeout(() => setCopied(false), 1800);
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
          Drag the button below into your browser&apos;s bookmarks bar (or{" "}
          right-click → Add to bookmarks). Then on any LinkedIn / Indeed /
          company careers page, click the bookmark and that job lands in
          your inbox — no copy-paste, no tab switching.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          {/* The actual draggable element. Browsers let users drag <a>
              tags with href onto the bookmarks bar; the title becomes
              the bookmark name. Click does nothing useful (it'd open the
              import page) — drag is the intended interaction. */}
          <a
            href={bookmarkletHref}
            onClick={(e) => e.preventDefault()}
            draggable
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-lg border border-amber-500/40 bg-amber-500/10 text-amber-300 text-sm font-medium hover:bg-amber-500/15 cursor-grab active:cursor-grabbing transition-colors"
            title="Drag me to your bookmarks bar"
          >
            <Bookmark className="h-4 w-4" />
            Save to JobHunt
          </a>
          <Button variant="ghost" size="sm" onClick={handleCopy} disabled={!origin}>
            {copied ? (
              <>
                <Check className="h-3.5 w-3.5 text-emerald-400" />
                Copied
              </>
            ) : (
              <>
                <Copy className="h-3.5 w-3.5" />
                Or copy URL
              </>
            )}
          </Button>
          <span className="text-xs text-muted-foreground">
            (paste into a new bookmark&apos;s URL field if drag doesn&apos;t work)
          </span>
        </div>

        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer hover:text-foreground">
            How it works
          </summary>
          <ul className="mt-2 space-y-1.5 pl-4 list-disc">
            <li>
              Bookmarklet reads the URL of whatever tab you&apos;re on, opens
              a new tab on this dashboard with that URL pre-loaded.
            </li>
            <li>
              The new tab auto-imports (parses with Claude, runs the
              apply-link resolver, scores against your profile) and
              redirects to your inbox when done. Takes ~15–25 s.
            </li>
            <li>
              You need to be logged into this dashboard for it to work —
              your session cookies are what authenticate the import.
            </li>
            <li>
              Works on LinkedIn / Indeed / Greenhouse / Lever / Ashby and
              any company careers page. If a page anti-bots the
              underlying scrape, we&apos;ll show you which step failed.
            </li>
          </ul>
        </details>
      </CardContent>
    </Card>
  );
}
