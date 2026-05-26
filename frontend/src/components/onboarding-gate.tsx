"use client";

/**
 * Gates the dashboard behind two prerequisites:
 *
 *   1. The user has set their name (currently empty on Supabase invite).
 *   2. The user has uploaded at least one resume.
 *
 * Without either of those, every downstream feature is degraded — scoring
 * has no profile to match against, tailoring has nothing to draw from,
 * cover-letter drafts can't address the candidate. So instead of letting
 * a new invitee land on an empty inbox and wonder why, we render a
 * step-by-step setup view until both are done. Once they are, the gate
 * gets out of the way and renders the dashboard normally.
 *
 * Pure client-side check using the existing TanStack Query hooks — no
 * backend changes needed. The gate auto-unblocks the moment the queries
 * refetch after the name save / resume upload mutations.
 */

import { useState } from "react";
import { useCurrentUser, useUpdateMe, useResumes, useUploadResume } from "@/hooks/use-api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Loader2, CheckCircle2, FileUp, User as UserIcon, ArrowRight } from "lucide-react";
import { useToast } from "@/components/ui/toast";

export function OnboardingGate({ children }: { children: React.ReactNode }) {
  const { data: user, isLoading: userLoading } = useCurrentUser();
  const { data: resumes, isLoading: resumesLoading } = useResumes();

  // Treat loading as 'don't render yet' rather than 'gate is open' — would
  // otherwise flash the children for a frame before swapping back.
  if (userLoading || resumesLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const hasName = !!(user?.name && user.name.trim().length > 0);
  const hasResume = (resumes?.length ?? 0) > 0;

  if (hasName && hasResume) {
    return <>{children}</>;
  }

  return <OnboardingFlow hasName={hasName} hasResume={hasResume} existingName={user?.name ?? ""} />;
}


function OnboardingFlow({
  hasName,
  hasResume,
  existingName,
}: {
  hasName: boolean;
  hasResume: boolean;
  existingName: string;
}) {
  const toast = useToast();
  const updateMe = useUpdateMe();
  const uploadResume = useUploadResume();

  const [name, setName] = useState(existingName);
  const [file, setFile] = useState<File | null>(null);

  // Active step: name first, then resume. Once name lands, the panel
  // shifts focus to resume without a page transition.
  const activeStep: 1 | 2 = !hasName ? 1 : 2;

  async function saveName() {
    const trimmed = name.trim();
    if (!trimmed) {
      toast.error("Add a name first", { description: "We use this when drafting cover letters and outreach." });
      return;
    }
    try {
      await updateMe.mutateAsync(trimmed);
      toast.success("Saved", { description: "Now drop your resume so we can tune your inbox." });
    } catch (e: any) {
      toast.error("Couldn't save", { description: e?.message || "Try again in a moment." });
    }
  }

  async function uploadAndContinue() {
    if (!file) {
      toast.error("Pick a file first", { description: "PDF or DOCX works." });
      return;
    }
    try {
      // version_name = filename without extension, tags blank — plenty
      // for first upload; user can rename later from the Resumes tab.
      const versionName = file.name.replace(/\.[^.]+$/, "");
      await uploadResume.mutateAsync({ file, versionName, tags: "" });
      toast.success("Resume uploaded", {
        description: "Reading it now — your inbox will populate in about a minute.",
      });
    } catch (e: any) {
      toast.error("Upload failed", { description: e?.message || "Try a different file." });
    }
  }

  return (
    <div className="max-w-2xl mx-auto py-4 sm:py-10 space-y-6">
      <div className="space-y-2 text-center">
        <h1 className="text-2xl sm:text-3xl font-semibold">Welcome — let&apos;s set you up</h1>
        <p className="text-sm text-muted-foreground max-w-md mx-auto">
          Two quick steps and your inbox starts scoring jobs against your background.
        </p>
      </div>

      <div className="flex items-center gap-3 justify-center text-xs font-medium">
        <StepDot n={1} active={activeStep === 1} done={hasName} />
        <div className="h-px w-12 bg-white/[0.08]" />
        <StepDot n={2} active={activeStep === 2} done={hasResume} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            {hasName ? (
              <CheckCircle2 className="h-5 w-5 text-emerald-400" />
            ) : (
              <UserIcon className="h-5 w-5" />
            )}
            What should we call you?
          </CardTitle>
          <CardDescription>
            Used in tailored cover letters and outreach messages.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-2">
            <Label htmlFor="onboarding-name">Your name</Label>
            <Input
              id="onboarding-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Olalekan Oderinlo"
              disabled={hasName}
              autoFocus={!hasName}
            />
          </div>
          {!hasName && (
            <Button onClick={saveName} disabled={updateMe.isPending || !name.trim()}>
              {updateMe.isPending ? (
                <><Loader2 className="h-4 w-4 animate-spin" /> Saving…</>
              ) : (
                <>Save name <ArrowRight className="h-4 w-4" /></>
              )}
            </Button>
          )}
        </CardContent>
      </Card>

      <Card className={hasName ? "" : "opacity-60 pointer-events-none"}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            {hasResume ? (
              <CheckCircle2 className="h-5 w-5 text-emerald-400" />
            ) : (
              <FileUp className="h-5 w-5" />
            )}
            Upload your resume
          </CardTitle>
          <CardDescription>
            PDF or DOCX. We extract your work history, skills, and bullets so
            every job in your inbox gets matched against your real background —
            not a generic profile. Takes 30–60 seconds after upload.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Input
            type="file"
            accept=".pdf,.docx,.doc"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            disabled={!hasName}
            autoFocus={hasName && !hasResume}
          />
          <Button
            onClick={uploadAndContinue}
            disabled={!hasName || uploadResume.isPending || !file}
          >
            {uploadResume.isPending ? (
              <><Loader2 className="h-4 w-4 animate-spin" /> Uploading…</>
            ) : (
              <>Upload &amp; continue <ArrowRight className="h-4 w-4" /></>
            )}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}


function StepDot({ n, active, done }: { n: number; active: boolean; done: boolean }) {
  return (
    <div
      className={[
        "inline-flex items-center justify-center h-6 w-6 rounded-full border text-[10px] transition-colors",
        done
          ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300"
          : active
            ? "bg-foreground text-background border-foreground"
            : "border-white/[0.08] text-muted-foreground",
      ].join(" ")}
    >
      {done ? <CheckCircle2 className="h-3.5 w-3.5" /> : n}
    </div>
  );
}
