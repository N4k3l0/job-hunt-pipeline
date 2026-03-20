"use client";

import { useState } from "react";
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
} from "lucide-react";
import { useImportJobUrl, useImportJobText } from "@/hooks/use-api";

export default function ImportPage() {
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");

  const importUrl = useImportJobUrl();
  const importText = useImportJobText();

  async function handleUrlImport() {
    if (!url.trim()) return;
    importUrl.mutate(url.trim(), {
      onSuccess: () => setUrl(""),
    });
  }

  async function handleTextImport() {
    if (!text.trim()) return;
    importText.mutate(
      { text: text.trim(), source: "manual" },
      { onSuccess: () => setText("") },
    );
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Import Job</h1>
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
                  Job queued for processing. It will appear in your inbox shortly.
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
                  Job queued for parsing. It will appear in your inbox once processed.
                </div>
              )}
              {importText.isError && (
                <p className="text-sm text-destructive">{importText.error.message}</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
