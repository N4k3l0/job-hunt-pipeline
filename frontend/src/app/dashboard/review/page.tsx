"use client";

import { useState } from "react";
import {
  Card, CardContent, CardHeader, CardTitle, CardAction, CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import {
  CheckCircle2, XCircle, FileText, Mail, MessageSquare, Download,
  Edit3, AlertCircle, Loader2, ExternalLink, MapPin, Building2, Globe, Copy, Check,
} from "lucide-react";
import { useReviewQueue, useApproveTailored, useDeleteTailored, useTailoredApplication } from "@/hooks/use-api";

export default function ReviewQueuePage() {
  const { data: queue, isLoading } = useReviewQueue();
  const approve = useApproveTailored();
  const deleteTailored = useDeleteTailored();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const copyText = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    setCopied(label);
    setTimeout(() => setCopied(null), 2000);
  };

  const items = queue ?? [];
  const selected = selectedId ? items.find((i: any) => i.id === selectedId) : items[0];

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Review Queue</h1>
          <p className="text-muted-foreground">Tailored applications ready for review</p>
        </div>
        <Card>
          <CardContent className="py-12 text-center">
            <FileText className="h-10 w-10 mx-auto text-muted-foreground/20 mb-3" />
            <p className="text-muted-foreground">No applications pending review.</p>
            <p className="text-sm text-muted-foreground/60 mt-1">
              Generate tailored materials from the Jobs Inbox.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const review = selected || items[0];

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Review Queue</h1>
          <p className="text-muted-foreground">{items.length} pending review</p>
        </div>
      </div>

      {/* Tabs for each pending item */}
      {items.length > 1 && (
        <div className="flex gap-2 overflow-x-auto pb-2">
          {items.map((item: any) => (
            <button
              key={item.id}
              onClick={() => setSelectedId(item.id)}
              className={`shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                review.id === item.id ? "bg-amber-500/10 text-amber-400 border border-amber-500/20" : "bg-white/[0.03] text-muted-foreground hover:bg-white/[0.06]"
              }`}
            >
              {item.job?.title ? `${item.job.title.slice(0, 30)}${item.job.title.length > 30 ? '...' : ''}` : item.job_id?.slice(0, 8)}
            </button>
          ))}
        </div>
      )}

      {/* Job Header Card */}
      <Card className="border-amber-500/20">
        <CardContent className="py-4">
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-2">
              <div>
                <h2 className="text-xl font-semibold">{review.job?.title || "Untitled Job"}</h2>
                <div className="flex items-center gap-3 mt-1 text-sm text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <Building2 className="h-3.5 w-3.5" />
                    {review.job?.company || "Unknown"}
                  </span>
                  {review.job?.location && (
                    <span className="flex items-center gap-1">
                      <MapPin className="h-3.5 w-3.5" />
                      {review.job.location}
                    </span>
                  )}
                  {review.job?.remote_type && (
                    <Badge variant="secondary" className="text-[10px] bg-emerald-500/10 text-emerald-400">
                      <Globe className="h-3 w-3 mr-0.5" />
                      {review.job.remote_type}
                    </Badge>
                  )}
                  {review.job?.salary_text && (
                    <span className="text-emerald-400 font-medium">{review.job.salary_text}</span>
                  )}
                </div>
              </div>
            </div>
            <div className="flex gap-2 shrink-0">
              {review.job?.job_url && (
                <Button variant="outline" size="sm" nativeButton={false}
                  render={<a href={review.job.job_url} target="_blank" rel="noopener" />}>
                  <ExternalLink className="h-3.5 w-3.5" /> View Posting
                </Button>
              )}
              {review.job?.apply_url && review.job.apply_url !== review.job.job_url && (
                <Button size="sm" nativeButton={false}
                  render={<a href={review.job.apply_url} target="_blank" rel="noopener" />}>
                  <ExternalLink className="h-3.5 w-3.5" /> Apply
                </Button>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2 items-start">
        {/* Left: Keywords + Fit */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Application Analysis</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {review.keyword_matches && (
              <>
                <div>
                  <span className="text-xs text-muted-foreground">Matched keywords:</span>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {(review.keyword_matches.matched || []).map((kw: string) => (
                      <Badge key={kw} variant="secondary" className="text-[10px] bg-emerald-500/10 text-emerald-400">{kw}</Badge>
                    ))}
                  </div>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">Gaps:</span>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {(review.keyword_matches.unmatched || []).map((kw: string) => (
                      <Badge key={kw} variant="secondary" className="text-[10px] bg-amber-500/10 text-amber-400">{kw}</Badge>
                    ))}
                  </div>
                </div>
              </>
            )}
            {review.validation_notes && (
              <>
                <Separator />
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <div className="flex items-center gap-1.5 mb-1.5">
                      <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                      <span className="text-xs font-medium">Strengths</span>
                    </div>
                    <ul className="space-y-1">
                      {(review.validation_notes.strongest_matches || []).map((s: string) => (
                        <li key={s} className="text-xs text-muted-foreground">{s}</li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <div className="flex items-center gap-1.5 mb-1.5">
                      <AlertCircle className="h-3.5 w-3.5 text-amber-400" />
                      <span className="text-xs font-medium">Gaps</span>
                    </div>
                    <ul className="space-y-1">
                      {(review.validation_notes.gaps || []).map((g: string) => (
                        <li key={g} className="text-xs text-muted-foreground">{g}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* Right: Tailored Materials */}
        <div className="space-y-4">
          <Tabs defaultValue="resume">
            <TabsList className="w-full">
              <TabsTrigger value="resume" className="flex-1"><FileText className="h-3.5 w-3.5 mr-1.5" />Resume</TabsTrigger>
              <TabsTrigger value="cover" className="flex-1"><Mail className="h-3.5 w-3.5 mr-1.5" />Cover</TabsTrigger>
              <TabsTrigger value="outreach" className="flex-1"><MessageSquare className="h-3.5 w-3.5 mr-1.5" />Outreach</TabsTrigger>
            </TabsList>

            <TabsContent value="resume">
              <Card>
                <CardContent className="pt-4">
                  <div className="flex justify-end mb-2">
                    <Button variant="ghost" size="sm"
                      onClick={() => copyText(review.tailored_summary || "", "resume")}>
                      {copied === "resume" ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                      {copied === "resume" ? "Copied" : "Copy"}
                    </Button>
                  </div>
                  <div className="bg-white/[0.02] rounded-lg p-4 text-sm leading-relaxed whitespace-pre-line">
                    {review.tailored_summary || "No tailored summary generated yet."}
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="cover">
              <Card>
                <CardContent className="pt-4">
                  <div className="flex justify-end mb-2">
                    <Button variant="ghost" size="sm"
                      onClick={() => copyText(review.cover_letter || "", "cover")}>
                      {copied === "cover" ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                      {copied === "cover" ? "Copied" : "Copy"}
                    </Button>
                  </div>
                  <div className="bg-white/[0.02] rounded-lg p-4 text-sm leading-relaxed whitespace-pre-line">
                    {review.cover_letter || "No cover letter generated yet."}
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="outreach">
              <Card>
                <CardContent className="pt-4">
                  <div className="flex justify-end mb-2">
                    <Button variant="ghost" size="sm"
                      onClick={() => copyText(review.recruiter_message || "", "outreach")}>
                      {copied === "outreach" ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                      {copied === "outreach" ? "Copied" : "Copy"}
                    </Button>
                  </div>
                  <div className="bg-white/[0.02] rounded-lg p-4 text-sm leading-relaxed whitespace-pre-line">
                    {review.recruiter_message || "No outreach message generated yet."}
                  </div>
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>

          {/* Actions */}
          <Card>
            <CardContent className="flex items-center justify-between py-3">
              <div className="flex gap-2">
                {review.tailored_resume_url && (
                  <Button variant="outline" size="sm" nativeButton={false}
                    render={<a href={review.tailored_resume_url} target="_blank" rel="noopener" />}>
                    <Download className="h-3.5 w-3.5" /> Download PDF
                  </Button>
                )}
              </div>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    if (confirm("Delete this application from the review queue?")) {
                      deleteTailored.mutate(review.id);
                      setSelectedId(null);
                    }
                  }}
                  disabled={deleteTailored.isPending}
                  className="text-red-400 hover:text-red-300 hover:border-red-500/30"
                >
                  {deleteTailored.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <XCircle className="h-3.5 w-3.5" />
                  )}
                  Delete
                </Button>
                <Button
                  size="sm"
                  onClick={() => approve.mutate(review.id)}
                  disabled={approve.isPending}
                >
                  {approve.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <CheckCircle2 className="h-3.5 w-3.5" />
                  )}
                  Approve
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
