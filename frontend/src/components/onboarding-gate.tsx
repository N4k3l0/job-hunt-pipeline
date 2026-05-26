"use client";

/**
 * Gates the dashboard behind three prerequisites:
 *
 *   1. The user has set their name (currently empty on Supabase invite).
 *   2. The user has uploaded at least one resume.
 *   3. The user has picked at least one preferred country (or "Worldwide").
 *
 * Without any of those, every downstream feature is degraded — scoring
 * has no profile to match against, tailoring has nothing to draw from,
 * the country filter has nothing to filter against. So instead of letting
 * a new invitee land on an empty inbox and wonder why, we render a
 * step-by-step setup view until all three are done. Once they are, the
 * gate gets out of the way and renders the dashboard normally.
 *
 * Pure client-side check using the existing TanStack Query hooks — no
 * backend changes needed. The gate auto-unblocks the moment the queries
 * refetch after each save.
 */

import { useState } from "react";
import {
  useCurrentUser,
  useUpdateMe,
  useResumes,
  useUploadResume,
  useProfile,
  useUpdateProfile,
  useCreateProfile,
} from "@/hooks/use-api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Loader2, CheckCircle2, FileUp, User as UserIcon, ArrowRight, Globe, Plus, X,
} from "lucide-react";
import { useToast } from "@/components/ui/toast";
import { COUNTRY_OPTIONS } from "@/lib/countries";

export function OnboardingGate({ children }: { children: React.ReactNode }) {
  const { data: user, isLoading: userLoading } = useCurrentUser();
  const { data: resumes, isLoading: resumesLoading } = useResumes();
  const { data: profile, isLoading: profileLoading } = useProfile();

  // Treat loading as 'don't render yet' rather than 'gate is open' — would
  // otherwise flash the children for a frame before swapping back.
  if (userLoading || resumesLoading || profileLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const hasName = !!(user?.name && user.name.trim().length > 0);
  const hasResume = (resumes?.length ?? 0) > 0;
  const hasCountries = (profile?.preferred_countries?.length ?? 0) > 0;

  if (hasName && hasResume && hasCountries) {
    return <>{children}</>;
  }

  return (
    <OnboardingFlow
      hasName={hasName}
      hasResume={hasResume}
      hasCountries={hasCountries}
      existingName={user?.name ?? ""}
      existingCountries={profile?.preferred_countries ?? []}
      hasProfile={!!profile}
    />
  );
}


function OnboardingFlow({
  hasName,
  hasResume,
  hasCountries,
  existingName,
  existingCountries,
  hasProfile,
}: {
  hasName: boolean;
  hasResume: boolean;
  hasCountries: boolean;
  existingName: string;
  existingCountries: string[];
  hasProfile: boolean;
}) {
  const toast = useToast();
  const updateMe = useUpdateMe();
  const uploadResume = useUploadResume();
  const updateProfile = useUpdateProfile();
  const createProfile = useCreateProfile();

  const [name, setName] = useState(existingName);
  const [file, setFile] = useState<File | null>(null);
  const [countries, setCountries] = useState<string[]>(existingCountries);

  // Active step progression: name → resume → countries. Once a step
  // lands the panel shifts focus to the next without a page transition.
  const activeStep: 1 | 2 | 3 = !hasName ? 1 : !hasResume ? 2 : 3;

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
        description: "Reading it now — pick your preferred countries to finish.",
      });
    } catch (e: any) {
      toast.error("Upload failed", { description: e?.message || "Try a different file." });
    }
  }

  async function saveCountries() {
    if (countries.length === 0) {
      toast.error("Pick at least one country", {
        description: "Or 'Worldwide / Remote' if you don't care about location.",
      });
      return;
    }
    try {
      const payload = { preferred_countries: countries };
      if (hasProfile) {
        await updateProfile.mutateAsync(payload);
      } else {
        // First-time setup — the resume parser creates the profile row,
        // but on very fresh accounts the row may not exist yet.
        await createProfile.mutateAsync(payload);
      }
      toast.success("All set", {
        description: "Loading your inbox.",
      });
    } catch (e: any) {
      toast.error("Couldn't save", { description: e?.message || "Try again in a moment." });
    }
  }

  function toggleCountry(code: string) {
    setCountries((prev) =>
      prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]
    );
  }

  return (
    <div className="ds-page-fade max-w-2xl mx-auto py-4 sm:py-10 space-y-6">
      {/* Brand-anchored hero — tiny teal "J" mark + welcome.
          Matches the sidebar brand from the design. */}
      <div className="space-y-3 text-center">
        <div className="flex justify-center">
          <div style={{
            width: 36, height: 36,
            borderRadius: 8,
            background: "var(--ds-accent)",
            color: "#04140f",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily: "var(--ds-font-mono)",
            fontWeight: 700,
            fontSize: 17,
            letterSpacing: "-0.04em",
          }}>J</div>
        </div>
        <h1 className="ds-h1" style={{ fontSize: 28 }}>Welcome — let&apos;s set you up</h1>
        <p className="ds-muted" style={{ fontSize: 14, maxWidth: 420, margin: "0 auto" }}>
          Three quick steps and your inbox starts scoring jobs against
          your background and target geographies.
        </p>
      </div>

      <div className="flex items-center gap-3 justify-center text-xs font-medium">
        <StepDot n={1} active={activeStep === 1} done={hasName} />
        <div className="h-px w-12 bg-white/[0.08]" />
        <StepDot n={2} active={activeStep === 2} done={hasResume} />
        <div className="h-px w-12 bg-white/[0.08]" />
        <StepDot n={3} active={activeStep === 3} done={hasCountries} />
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

      {/* Step 3 — Preferred countries. Greyed until resume lands. */}
      <Card className={hasResume ? "" : "opacity-60 pointer-events-none"}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            {hasCountries ? (
              <CheckCircle2 className="h-5 w-5 text-emerald-400" />
            ) : (
              <Globe className="h-5 w-5" />
            )}
            Where do you want jobs from?
          </CardTitle>
          <CardDescription>
            Pick one or more. Jobs from anywhere else get filtered out of
            your inbox. Pick <span className="text-foreground">Worldwide / Remote</span> if
            you don&apos;t mind the country as long as the role is remote.
            You can change this anytime under Profile → Preferences.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2 min-h-[34px]">
            {countries.map((code) => {
              const meta = COUNTRY_OPTIONS.find((o) => o.code === code);
              return (
                <Badge key={code} variant="outline" className="gap-1 pr-1.5 text-sm py-1">
                  {meta ? meta.name : code}
                  <button
                    onClick={() => toggleCountry(code)}
                    className="ml-1 hover:text-destructive"
                    aria-label={`Remove ${meta?.name ?? code}`}
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </Badge>
              );
            })}
            {countries.length === 0 && (
              <span className="text-sm text-muted-foreground self-center">
                No countries selected yet
              </span>
            )}
          </div>

          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button variant="outline" size="sm" disabled={!hasResume}>
                  <Plus className="h-4 w-4" />
                  Add country
                </Button>
              }
            />
            <DropdownMenuContent align="start" className="max-h-[340px] overflow-y-auto w-[280px]">
              {Object.entries(
                COUNTRY_OPTIONS.reduce<Record<string, typeof COUNTRY_OPTIONS>>((acc, c) => {
                  (acc[c.group] ??= []).push(c);
                  return acc;
                }, {})
              ).map(([group, items]) => (
                <div key={group} className="px-1">
                  <div className="px-2 py-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
                    {group}
                  </div>
                  {items.map((c) => {
                    const selected = countries.includes(c.code);
                    return (
                      <DropdownMenuItem
                        key={c.code}
                        onClick={() => toggleCountry(c.code)}
                        className="flex items-center justify-between gap-2"
                      >
                        <span className="flex items-center gap-2">
                          {selected && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />}
                          {c.name}
                        </span>
                        <span className="text-[10px] text-muted-foreground">
                          {c.coverage === "strong" ? "well covered" : "remote-only"}
                        </span>
                      </DropdownMenuItem>
                    );
                  })}
                </div>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          <p className="text-xs text-muted-foreground leading-relaxed">
            <span className="text-foreground">well covered</span> means we
            pull jobs directly from sources serving that country.
            {" "}<span className="text-foreground">remote-only</span> means
            we&apos;ll surface jobs that are remote-eligible and mention
            the country — local-only listings may be sparse. You can paste
            any local job URL on the Import page to add it manually.
          </p>

          <Button
            onClick={saveCountries}
            disabled={
              !hasResume ||
              updateProfile.isPending ||
              createProfile.isPending ||
              countries.length === 0
            }
          >
            {(updateProfile.isPending || createProfile.isPending) ? (
              <><Loader2 className="h-4 w-4 animate-spin" /> Saving…</>
            ) : (
              <>Save &amp; open inbox <ArrowRight className="h-4 w-4" /></>
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
