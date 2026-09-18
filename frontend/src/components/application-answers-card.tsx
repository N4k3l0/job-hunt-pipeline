"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ClipboardList, Loader2 } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";
import { useProfile, useUpdateProfile } from "@/hooks/use-api";
import { COUNTRY_OPTIONS } from "@/lib/countries";

type WorkRight = "" | "work_visa" | "need_sponsorship";

const WORK_RIGHT_LABELS: { value: WorkRight; label: string }[] = [
  { value: "work_visa", label: "I can work there already" },
  { value: "need_sponsorship", label: "I'd need sponsorship" },
];

function countryName(code: string) {
  return COUNTRY_OPTIONS.find((option) => option.code === code)?.name ?? code;
}

/** The answers every application form asks for. Answered once here, or on
 *  the first form that asks, then filled in automatically after that. */
export function ApplicationAnswersCard() {
  const toast = useToast();
  const { data: profile, isLoading } = useProfile();
  const update = useUpdateProfile();

  const [phone, setPhone] = useState("");
  const [location, setLocation] = useState("");
  const [earliestStart, setEarliestStart] = useState("");
  const [relocation, setRelocation] = useState<"" | "yes" | "no">("");
  const [languages, setLanguages] = useState("");
  const [workRights, setWorkRights] = useState<Record<string, WorkRight>>({});

  useEffect(() => {
    if (!profile) return;
    setPhone(profile.phone ?? "");
    setLocation(profile.current_location ?? "");
    setEarliestStart(profile.earliest_start ?? "");
    setRelocation(profile.open_to_relocation === null || profile.open_to_relocation === undefined
      ? "" : profile.open_to_relocation ? "yes" : "no");
    setLanguages((profile.languages ?? []).join(", "));
    setWorkRights((profile.visa_statuses ?? {}) as Record<string, WorkRight>);
  }, [profile]);

  // Where this user actually applies: where they live, plus the countries
  // they picked, plus anywhere they've already answered for.
  const countries = Array.from(new Set([
    ...(profile?.home_country ? [profile.home_country] : []),
    ...(profile?.preferred_countries ?? []),
    ...Object.keys(workRights),
  ])).filter((code) => code && code !== "WW");

  async function save() {
    try {
      await update.mutateAsync({
        phone: phone.trim() || null,
        current_location: location.trim() || null,
        earliest_start: earliestStart.trim() || null,
        open_to_relocation: relocation === "" ? null : relocation === "yes",
        languages: languages.split(",").map((l) => l.trim()).filter(Boolean),
        visa_statuses: Object.fromEntries(Object.entries(workRights).filter(([, v]) => v)),
      });
      toast.success("Saved", { description: "Applications will fill these in from now on." });
    } catch (e) {
      toast.error("Couldn't save", { description: e instanceof Error ? e.message : undefined });
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ClipboardList className="h-5 w-5" />
          Application answers
        </CardTitle>
        <CardDescription>
          Every application form asks for these. Answer them once and the app fills them in, however each
          company words the question.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading ? (
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="answers-phone">Phone number</Label>
                <Input id="answers-phone" value={phone} onChange={(e) => setPhone(e.target.value)}
                       placeholder="+234 800 000 0000" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="answers-location">Where you live</Label>
                <Input id="answers-location" value={location} onChange={(e) => setLocation(e.target.value)}
                       placeholder="Lagos, Nigeria" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="answers-start">Earliest you can start</Label>
                <Input id="answers-start" value={earliestStart} onChange={(e) => setEarliestStart(e.target.value)}
                       placeholder="Immediately, or 1 month" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="answers-languages">Languages you speak</Label>
                <Input id="answers-languages" value={languages} onChange={(e) => setLanguages(e.target.value)}
                       placeholder="English, French" />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label>Would you move for a job?</Label>
              <div className="flex gap-2">
                {[{ v: "yes", l: "Yes" }, { v: "no", l: "No" }].map(({ v, l }) => (
                  <button
                    key={v}
                    type="button"
                    className="ds-chip"
                    data-active={relocation === v}
                    onClick={() => setRelocation(relocation === v ? "" : (v as "yes" | "no"))}
                  >
                    {l}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <Label>Where you can work</Label>
              <p className="text-xs text-muted-foreground">
                Forms ask this for their own country. Answer per country and it never gets asked twice.
              </p>
              {countries.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Pick your countries under Preferences first.
                </p>
              ) : (
                <div className="space-y-2">
                  {countries.map((code) => (
                    <div key={code} className="flex flex-wrap items-center gap-2">
                      <span className="text-sm" style={{ minWidth: 140 }}>{countryName(code)}</span>
                      {WORK_RIGHT_LABELS.map(({ value, label }) => (
                        <button
                          key={value}
                          type="button"
                          className="ds-chip"
                          data-active={workRights[code] === value}
                          onClick={() =>
                            setWorkRights((current) => ({
                              ...current,
                              [code]: current[code] === value ? "" : value,
                            }))
                          }
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  ))}
                </div>
              )}
            </div>

            <Button onClick={save} disabled={update.isPending}>
              {update.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Save answers
            </Button>
          </>
        )}
      </CardContent>
    </Card>
  );
}

const PROMPT_DISMISSED_KEY = "application-answers-prompt-dismissed";

function readDismissed() {
  try {
    return window.localStorage.getItem(PROMPT_DISMISSED_KEY) === "1";
  } catch {
    return false;
  }
}

/** Shown once setup is done, until the answers are in. Dismissible: it
 *  never blocks anyone who set up before this existed. */
export function ApplicationAnswersPrompt() {
  const { data: profile } = useProfile();
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => setDismissed(readDismissed()), []);

  const home = profile?.home_country;
  const answered = Boolean(
    profile?.phone && profile?.current_location && home && (profile?.visa_statuses ?? {})[home],
  );
  if (dismissed || !profile || answered) return null;

  function dismiss() {
    try {
      window.localStorage.setItem(PROMPT_DISMISSED_KEY, "1");
    } catch {
      // Storage blocked; the prompt comes back next visit.
    }
    setDismissed(true);
  }

  return (
    <div
      className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border px-4 py-3"
      style={{ borderColor: "var(--ds-line)", background: "var(--ds-bg-elev-1)" }}
    >
      <ClipboardList className="h-4 w-4 shrink-0 text-muted-foreground" />
      <div className="min-w-[200px] flex-1 text-sm">
        <span className="font-medium">Answer five questions once</span>{" "}
        <span className="text-muted-foreground">
          Phone, where you live, when you can start, and where you can work. Applications fill them in for you
          after that.
        </span>
      </div>
      <Button size="sm" render={<Link href="/dashboard/profile?tab=preferences" />}>Answer them</Button>
      <Button size="sm" variant="ghost" onClick={dismiss}>Later</Button>
    </div>
  );
}
