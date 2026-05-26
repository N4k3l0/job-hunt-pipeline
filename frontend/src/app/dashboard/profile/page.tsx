"use client";

import { useState, useEffect, useRef } from "react";
import {
  Card, CardContent, CardHeader, CardTitle, CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import {
  User, Upload, FileText, Plus, X, Globe, DollarSign, Search,
  Briefcase, GraduationCap, Loader2, CheckCircle2, Trash2, Circle, ArrowRight,
  Sparkles, FileSignature, Quote,
} from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { OperationProgress } from "@/components/operation-progress";
import {
  useProfile, useCreateProfile, useUpdateProfile,
  useResumes, useUploadResume, useDeleteResume,
  useWorkHistory, useSkills, useBullets,
  useCurrentUser, useUpdateMe, useRescoreInbox,
  useSampleApplications, useCreateSampleApplication, useDeleteSampleApplication,
} from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";

type SetupStep = {
  id: string;
  label: string;
  done: boolean;
  tab: "profile" | "resumes" | "preferences";
};

function SetupChecklist({
  steps,
  onJump,
  dismissed,
  onDismiss,
}: {
  steps: SetupStep[];
  onJump: (tab: SetupStep["tab"]) => void;
  dismissed: boolean;
  onDismiss: () => void;
}) {
  const doneCount = steps.filter((s) => s.done).length;
  const total = steps.length;
  if (doneCount === total || dismissed) return null;
  const pct = Math.round((doneCount / total) * 100);
  const next = steps.find((s) => !s.done);
  return (
    <div className="rounded-xl border border-amber-500/15 bg-gradient-to-br from-amber-500/[0.06] via-amber-500/[0.02] to-transparent p-4 sm:p-5 relative">
      <button
        onClick={onDismiss}
        className="absolute top-3 right-3 text-muted-foreground/40 hover:text-muted-foreground transition-colors"
        aria-label="Dismiss setup checklist"
      >
        <X className="h-3.5 w-3.5" />
      </button>
      <div className="flex items-center gap-2 mb-1">
        <span className="text-xs uppercase tracking-[0.1em] text-amber-400 font-semibold">
          Set up your profile
        </span>
        <span className="text-xs text-muted-foreground tabular-nums">
          {doneCount} of {total}
        </span>
      </div>
      <p className="text-sm text-muted-foreground mb-3">
        {next
          ? <>Next: <span className="text-foreground font-medium">{next.label}</span> — better matches and tailored applications.</>
          : "All set."}
      </p>
      {/* progress bar */}
      <div className="h-1 w-full rounded-full bg-white/[0.05] overflow-hidden mb-4">
        <div
          className="h-full bg-amber-400 transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <ul className="grid gap-1.5 sm:grid-cols-2">
        {steps.map((s) => (
          <li key={s.id}>
            <button
              onClick={() => onJump(s.tab)}
              className="w-full flex items-center gap-2 text-left text-sm py-1.5 group"
            >
              {s.done ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
              ) : (
                <Circle className="h-4 w-4 text-muted-foreground/40 shrink-0" />
              )}
              <span
                className={
                  s.done
                    ? "text-muted-foreground line-through decoration-emerald-500/30"
                    : "text-foreground/80 group-hover:text-amber-400 transition-colors"
                }
              >
                {s.label}
              </span>
              {!s.done && (
                <ArrowRight className="h-3 w-3 ml-auto opacity-0 group-hover:opacity-100 text-amber-400 transition-opacity" />
              )}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

// Curated ISO 3166-1 alpha-2 list — the regions a Nigeria-based AI/PM
// candidate is most likely to target. Ordered by 'sponsorship-friendly
// tech market' priority rather than alphabetical, so the most useful
// picks (NL/DE/UK/IE/US) sit at the top of the dropdown.
const COUNTRY_OPTIONS: { code: string; name: string; group: string }[] = [
  // High-priority sponsorship destinations
  { code: "NL", name: "Netherlands", group: "Europe" },
  { code: "DE", name: "Germany", group: "Europe" },
  { code: "IE", name: "Ireland", group: "Europe" },
  { code: "GB", name: "United Kingdom", group: "Europe" },
  { code: "US", name: "United States", group: "Americas" },
  { code: "CA", name: "Canada", group: "Americas" },
  // Rest of Europe
  { code: "FR", name: "France", group: "Europe" },
  { code: "ES", name: "Spain", group: "Europe" },
  { code: "PT", name: "Portugal", group: "Europe" },
  { code: "IT", name: "Italy", group: "Europe" },
  { code: "BE", name: "Belgium", group: "Europe" },
  { code: "LU", name: "Luxembourg", group: "Europe" },
  { code: "AT", name: "Austria", group: "Europe" },
  { code: "CH", name: "Switzerland", group: "Europe" },
  { code: "SE", name: "Sweden", group: "Europe" },
  { code: "DK", name: "Denmark", group: "Europe" },
  { code: "NO", name: "Norway", group: "Europe" },
  { code: "FI", name: "Finland", group: "Europe" },
  { code: "IS", name: "Iceland", group: "Europe" },
  { code: "PL", name: "Poland", group: "Europe" },
  { code: "CZ", name: "Czech Republic", group: "Europe" },
  { code: "EE", name: "Estonia", group: "Europe" },
  { code: "LV", name: "Latvia", group: "Europe" },
  { code: "LT", name: "Lithuania", group: "Europe" },
  // Asia-Pacific
  { code: "AU", name: "Australia", group: "Asia-Pacific" },
  { code: "NZ", name: "New Zealand", group: "Asia-Pacific" },
  { code: "SG", name: "Singapore", group: "Asia-Pacific" },
  { code: "JP", name: "Japan", group: "Asia-Pacific" },
  { code: "AE", name: "United Arab Emirates", group: "Asia-Pacific" },
  // Remote-anywhere proxy
  { code: "WW", name: "Worldwide / Remote", group: "Other" },
];


export default function ProfilePage() {
  // Profile data
  const { data: profile, isLoading: profileLoading } = useProfile();
  const createProfile = useCreateProfile();
  const updateProfile = useUpdateProfile();
  const { data: currentUser } = useCurrentUser();
  const updateMe = useUpdateMe();
  const toast = useToast();
  const [displayName, setDisplayName] = useState("");
  useEffect(() => {
    if (currentUser?.name) setDisplayName(currentUser.name);
  }, [currentUser?.name]);

  // Resume data
  const { data: resumes, isLoading: resumesLoading } = useResumes();
  const { data: workHistory } = useWorkHistory();
  const { data: skills } = useSkills();
  const { data: bullets } = useBullets();
  const uploadResume = useUploadResume();
  const deleteResume = useDeleteResume();
  const rescoreInbox = useRescoreInbox();

  // Form state
  const [headline, setHeadline] = useState("");
  const [summary, setSummary] = useState("");
  const [linkedin, setLinkedin] = useState("");
  const [portfolio, setPortfolio] = useState("");
  const [targetRoles, setTargetRoles] = useState<string[]>([]);
  const [countries, setCountries] = useState<string[]>([]);
  const [salaryMin, setSalaryMin] = useState("");
  const [salaryMax, setSalaryMax] = useState("");
  const [salaryCurrency, setSalaryCurrency] = useState("USD");
  const [remotePref, setRemotePref] = useState("any");
  const [searchKeywords, setSearchKeywords] = useState<string[]>([]);
  const [blockedSources, setBlockedSources] = useState<string[]>([]);
  const [newRole, setNewRole] = useState("");
  // newCountry / addCountry removed — country picker is now a
  // DropdownMenu of real ISO countries (see Target Countries card).
  const [newKeyword, setNewKeyword] = useState("");

  // Resume upload state
  const [versionName, setVersionName] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  // Populate form when profile loads
  useEffect(() => {
    if (profile) {
      setHeadline(profile.headline || "");
      setSummary(profile.master_summary || "");
      setLinkedin(profile.links?.linkedin || "");
      setPortfolio(profile.links?.portfolio || "");
      setTargetRoles(profile.target_roles || []);
      setCountries(profile.preferred_countries || []);
      setSalaryMin(profile.salary_min?.toString() || "");
      setSalaryMax(profile.salary_max?.toString() || "");
      setSalaryCurrency(profile.salary_currency || "USD");
      setRemotePref(profile.remote_preference || "any");
      setSearchKeywords((profile as any).search_keywords || []);
      setBlockedSources(profile.blocked_sources || []);
    }
  }, [profile]);

  const [profileSaved, setProfileSaved] = useState(false);
  const [prefsSaved, setPrefsSaved] = useState(false);
  const [activeTab, setActiveTab] = useState<"profile" | "resumes" | "preferences">("profile");
  const [setupDismissed, setSetupDismissed] = useState(false);

  // Compute completeness — drives the setup checklist banner. Each step is a
  // "best practice" so partial setups still get matches but the user knows
  // what's missing.
  const setupSteps: SetupStep[] = [
    { id: "resume", label: "Upload your resume", done: !!resumes && resumes.length > 0, tab: "resumes" },
    { id: "headline", label: "Add a professional headline", done: !!profile?.headline?.trim(), tab: "profile" },
    { id: "summary", label: "Write a master summary", done: !!profile?.master_summary?.trim(), tab: "profile" },
    { id: "roles", label: "Pick target roles", done: (profile?.target_roles?.length ?? 0) > 0, tab: "preferences" },
    { id: "regions", label: "Pick preferred regions", done: (profile?.preferred_countries?.length ?? 0) > 0, tab: "preferences" },
    { id: "salary", label: "Set salary expectations", done: !!profile?.salary_min || !!profile?.salary_max, tab: "preferences" },
  ];

  async function handleSaveProfile() {
    const data = {
      headline,
      master_summary: summary,
      links: { linkedin, portfolio },
    };

    if (profile) {
      updateProfile.mutate(data as any, { onSuccess: () => { setProfileSaved(true); setTimeout(() => setProfileSaved(false), 3000); } });
    } else {
      createProfile.mutate(data as any, { onSuccess: () => { setProfileSaved(true); setTimeout(() => setProfileSaved(false), 3000); } });
    }
  }

  function addKeyword() {
    if (newKeyword.trim() && !searchKeywords.includes(newKeyword.trim())) {
      setSearchKeywords([...searchKeywords, newKeyword.trim()]);
      setNewKeyword("");
    }
  }

  async function handleSavePreferences() {
    const data = {
      target_roles: targetRoles,
      preferred_countries: countries,
      search_keywords: searchKeywords,
      salary_min: salaryMin ? parseInt(salaryMin) : null,
      salary_max: salaryMax ? parseInt(salaryMax) : null,
      salary_currency: salaryCurrency,
      remote_preference: remotePref,
      blocked_sources: blockedSources,
    };

    if (profile) {
      updateProfile.mutate(data as any, { onSuccess: () => { setPrefsSaved(true); setTimeout(() => setPrefsSaved(false), 3000); } });
    } else {
      createProfile.mutate(data as any, { onSuccess: () => { setPrefsSaved(true); setTimeout(() => setPrefsSaved(false), 3000); } });
    }
  }

  async function handleUploadResume() {
    if (!selectedFile) return;
    // Version name is optional — if the user didn't type one, fall back
    // to the file's basename. Only the file actually matters; the label
    // is just for "which one is this?" in the Resumes list later.
    const effectiveName =
      versionName.trim() ||
      selectedFile.name.replace(/\.[^.]+$/, "") ||
      "Resume";
    uploadResume.mutate(
      { file: selectedFile, versionName: effectiveName, tags: "" },
      {
        onSuccess: () => {
          setSelectedFile(null);
          setVersionName("");
          if (fileInputRef.current) fileInputRef.current.value = "";
        },
      }
    );
  }

  function addRole() {
    if (newRole.trim() && !targetRoles.includes(newRole.trim())) {
      setTargetRoles([...targetRoles, newRole.trim()]);
      setNewRole("");
    }
  }

  const isSavingProfile = createProfile.isPending || updateProfile.isPending;

  return (
    <div className="space-y-5 sm:space-y-6 max-w-4xl">
      <div>
        <h1 className="font-display text-2xl sm:text-3xl font-semibold tracking-tight">Profile</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Powers job scoring and resume tailoring.
        </p>
      </div>

      <SetupChecklist
        steps={setupSteps}
        onJump={(tab) => {
          setActiveTab(tab);
          // Make sure the user sees the tab — scroll the main pane to top so
          // the form is in view, not buried below the checklist.
          requestAnimationFrame(() => {
            document.querySelector("main")?.scrollTo({ top: 0, behavior: "smooth" });
          });
        }}
        dismissed={setupDismissed}
        onDismiss={() => setSetupDismissed(true)}
      />

      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as "profile" | "resumes" | "preferences")}>
        <TabsList>
          <TabsTrigger value="profile">
            <User className="h-4 w-4 mr-1.5" />
            Profile
          </TabsTrigger>
          <TabsTrigger value="resumes">
            <FileText className="h-4 w-4 mr-1.5" />
            Resumes
          </TabsTrigger>
          <TabsTrigger value="preferences">
            <Globe className="h-4 w-4 mr-1.5" />
            Preferences
          </TabsTrigger>
        </TabsList>

        {/* ── Profile Tab ────────────────────────────────────────── */}
        <TabsContent value="profile" className="space-y-4 mt-4">
          {/* Display name — drives the dashboard greeting. Without this set,
              we fall back to nothing rather than the email local-part. */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <User className="h-5 w-5" />
                Display Name
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="space-y-2">
                <Label htmlFor="displayName">Your name</Label>
                <Input
                  id="displayName"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="e.g. Alex Morgan"
                />
                <p className="text-xs text-muted-foreground">
                  Shown in the dashboard greeting. Just your first name will be used.
                </p>
              </div>
              <Button
                size="sm"
                disabled={updateMe.isPending || !displayName.trim() || displayName.trim() === currentUser?.name}
                onClick={() =>
                  updateMe.mutate(displayName.trim(), {
                    onSuccess: () => toast.success("Name updated"),
                    onError: (e: any) => toast.error("Couldn't save name", { description: e?.message }),
                  })
                }
              >
                {updateMe.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                {updateMe.isPending ? "Saving…" : "Save name"}
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Briefcase className="h-5 w-5" />
                Professional Info
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="headline">Professional Headline</Label>
                <Input
                  id="headline"
                  value={headline}
                  onChange={(e) => setHeadline(e.target.value)}
                  placeholder="e.g. Senior Product Manager | AI/ML | 8 years B2B SaaS"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="summary">Summary</Label>
                <textarea
                  id="summary"
                  value={summary}
                  onChange={(e) => setSummary(e.target.value)}
                  className="flex min-h-[120px] w-full rounded-lg border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  placeholder="Your professional summary..."
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="linkedin">LinkedIn URL</Label>
                  <Input
                    id="linkedin"
                    value={linkedin}
                    onChange={(e) => setLinkedin(e.target.value)}
                    placeholder="https://linkedin.com/in/..."
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="portfolio">Portfolio URL</Label>
                  <Input
                    id="portfolio"
                    value={portfolio}
                    onChange={(e) => setPortfolio(e.target.value)}
                    placeholder="https://..."
                  />
                </div>
              </div>
              <div className="flex items-center gap-3">
                <Button onClick={handleSaveProfile} disabled={isSavingProfile}>
                  {isSavingProfile ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  {isSavingProfile ? "Saving..." : "Save Profile"}
                </Button>
                {profileSaved && (
                  <span className="flex items-center gap-1.5 text-sm text-emerald-400">
                    <CheckCircle2 className="h-4 w-4" /> Saved
                  </span>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Work History */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <GraduationCap className="h-5 w-5" />
                Work History
              </CardTitle>
              <CardDescription>
                Parsed from your uploaded resumes
              </CardDescription>
            </CardHeader>
            <CardContent>
              {!workHistory || workHistory.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-4">
                  Upload a resume to auto-populate your work history.
                </p>
              ) : (
                <div className="space-y-4">
                  {workHistory.map((entry: any) => (
                    <div key={entry.id} className="rounded-lg border border-white/[0.06] p-4">
                      <div className="flex items-start justify-between">
                        <div>
                          <h4 className="text-sm font-semibold">{entry.title}</h4>
                          <p className="text-sm text-muted-foreground">{entry.company}</p>
                          {(entry.start_date || entry.end_date) && (
                            <p className="text-xs text-muted-foreground mt-0.5">
                              {entry.start_date} — {entry.end_date || "Present"}
                            </p>
                          )}
                        </div>
                        {entry.domain_tags?.length > 0 && (
                          <div className="flex gap-1">
                            {entry.domain_tags.map((tag: string) => (
                              <Badge key={tag} variant="outline" className="text-xs">{tag}</Badge>
                            ))}
                          </div>
                        )}
                      </div>
                      {entry.bullets?.length > 0 && (
                        <ul className="mt-2 space-y-1">
                          {entry.bullets.map((b: string, i: number) => (
                            <li key={i} className="text-sm text-foreground/70 flex items-start gap-2">
                              <span className="text-muted-foreground mt-0.5 shrink-0">-</span>
                              {b}
                            </li>
                          ))}
                        </ul>
                      )}
                      {entry.skills?.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-2">
                          {entry.skills.map((s: string) => (
                            <Badge key={s} variant="secondary" className="text-xs">{s}</Badge>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Skills */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Briefcase className="h-5 w-5" />
                Skills
              </CardTitle>
              <CardDescription>
                Extracted from your resume and profile
              </CardDescription>
            </CardHeader>
            <CardContent>
              {!skills || skills.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-4">
                  No skills yet. Upload a resume to extract them.
                </p>
              ) : (
                <div className="space-y-3">
                  {["technical", "domain", "tool", "soft"].map((category) => {
                    const categorySkills = skills.filter((s: any) => s.category === category);
                    if (categorySkills.length === 0) return null;
                    return (
                      <div key={category}>
                        <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1.5 font-medium">
                          {category}
                        </p>
                        <div className="flex flex-wrap gap-1.5">
                          {categorySkills.map((s: any) => (
                            <Badge key={s.id} variant="secondary" className="text-xs">
                              {s.skill_name}
                              {s.proficiency && (
                                <span className="text-muted-foreground ml-1">· {s.proficiency}</span>
                              )}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Bullet Bank */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FileText className="h-5 w-5" />
                Bullet Bank
              </CardTitle>
              <CardDescription>
                {bullets?.length || 0} achievement bullets extracted from your resume
              </CardDescription>
            </CardHeader>
            <CardContent>
              {!bullets || bullets.length === 0 ? (
                <EmptyState
                  icon={Sparkles}
                  title="No bullets yet"
                  description="Upload a resume on the Resumes tab — we extract your strongest achievement lines and store them here for tailoring."
                />
              ) : (
                <div className="space-y-1.5">
                  {bullets.map((b: any) => (
                    <div key={b.id} className="flex items-start gap-2 rounded-lg px-3 py-2 hover:bg-white/[0.02]">
                      <span className="text-muted-foreground mt-0.5 shrink-0">-</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm">{b.text}</p>
                        {b.keywords?.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-1">
                            {b.keywords.slice(0, 5).map((kw: string) => (
                              <Badge key={kw} variant="outline" className="text-xs">{kw}</Badge>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Resumes Tab ────────────────────────────────────────── */}
        <TabsContent value="resumes" className="space-y-4 mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Upload Resume</CardTitle>
              <CardDescription>
                Upload PDF or DOCX. The system will parse it into your structured profile.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="border-2 border-dashed border-white/[0.08] rounded-lg p-8 text-center">
                <Upload className="h-8 w-8 mx-auto text-muted-foreground mb-3" />

                {selectedFile ? (
                  <p className="text-sm font-medium mb-1 text-emerald-400">
                    {selectedFile.name} ({(selectedFile.size / 1024 / 1024).toFixed(1)} MB)
                  </p>
                ) : (
                  <p className="text-sm font-medium mb-1">
                    Click to select your resume
                  </p>
                )}
                <p className="text-xs text-muted-foreground mb-4">
                  PDF or DOCX, max 10MB
                </p>

                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  className="hidden"
                  onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
                />

                <div className="flex items-center justify-center gap-3 flex-wrap">
                  <Button variant="outline" onClick={() => fileInputRef.current?.click()}>
                    Choose file
                  </Button>
                  <Input
                    type="text"
                    value={versionName}
                    onChange={(e) => setVersionName(e.target.value)}
                    placeholder="Optional label (e.g. PM-General) — defaults to filename"
                    className="max-w-xs"
                  />
                  <Button
                    onClick={handleUploadResume}
                    disabled={uploadResume.isPending || !selectedFile}
                  >
                    {uploadResume.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Upload className="h-4 w-4" />
                    )}
                    {uploadResume.isPending ? "Uploading..." : "Upload & Parse"}
                  </Button>
                </div>

                <div className="mt-3">
                  <OperationProgress
                    active={uploadResume.isPending}
                    title="Parsing your resume"
                    description="We read the file, extract your structured profile (work history, skills, education, bullets), then score every job in your inbox against the fresh profile."
                    stages={[
                      { label: "Uploading the file", durationMs: 1500, tip: "Pushing the PDF / DOCX to storage." },
                      { label: "Reading your resume", durationMs: 9000, tip: "Pulling out work history, skills, education, and achievement bullets — never inventing anything." },
                      { label: "Building your structured profile", durationMs: 3000, tip: "Saving each section to its own table so the tailor service can pull from them later." },
                      { label: "Scoring your inbox", durationMs: 3500, tip: "Re-scoring every job against the new profile so the inbox sort reflects your latest skills." },
                    ]}
                  />
                </div>

                {uploadResume.isSuccess && (
                  <p className="text-sm text-emerald-400 mt-3 flex items-center justify-center gap-1.5">
                    <CheckCircle2 className="h-4 w-4" />
                    Resume uploaded + parsed. Your inbox has been rescored.
                  </p>
                )}
                {uploadResume.isError && (
                  <p className="text-sm text-destructive mt-3">
                    {uploadResume.error.message}
                  </p>
                )}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Your Resumes</CardTitle>
            </CardHeader>
            <CardContent>
              {resumesLoading ? (
                <div className="flex justify-center py-6">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : !resumes || resumes.length === 0 ? (
                <EmptyState
                  icon={FileSignature}
                  title="No resumes yet"
                  description="Drop a PDF or DOCX above. We parse it into structured profile data, then use it to tailor every application."
                />
              ) : (
                <div className="space-y-2">
                  {resumes.map((resume: any) => (
                    <div
                      key={resume.id}
                      className="flex items-center justify-between rounded-lg border border-white/[0.06] px-4 py-3"
                    >
                      <div className="flex items-center gap-3">
                        <FileText className="h-5 w-5 text-muted-foreground" />
                        <div>
                          <p className="text-sm font-medium">{resume.version_name}</p>
                          <div className="flex items-center gap-2 mt-0.5">
                            <span className="text-xs text-muted-foreground uppercase">{resume.source_type}</span>
                            {resume.parsed_at && (
                              <Badge variant="secondary" className="text-xs">Parsed</Badge>
                            )}
                            {!resume.parsed_at && (
                              <Badge variant="outline" className="text-xs text-amber-400 border-amber-500/20">Parsing...</Badge>
                            )}
                            {resume.tags?.map((tag: string) => (
                              <Badge key={tag} variant="outline" className="text-xs">{tag}</Badge>
                            ))}
                          </div>
                        </div>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon-xs"
                        onClick={() => deleteResume.mutate(resume.id)}
                      >
                        <Trash2 className="h-4 w-4 text-muted-foreground hover:text-destructive" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          <WritingSamplesCard />
        </TabsContent>

        {/* ── Preferences Tab ────────────────────────────────────── */}
        <TabsContent value="preferences" className="space-y-4 mt-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Briefcase className="h-5 w-5" />
                Target Roles
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap gap-2">
                {targetRoles.map((role) => (
                  <Badge key={role} variant="secondary" className="gap-1 pr-1.5 text-sm py-1">
                    {role}
                    <button
                      onClick={() => setTargetRoles(targetRoles.filter((r) => r !== role))}
                      className="ml-1 hover:text-destructive"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </Badge>
                ))}
                {targetRoles.length === 0 && (
                  <span className="text-sm text-muted-foreground">No roles added yet</span>
                )}
              </div>
              <div className="flex gap-2">
                <Input
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value)}
                  placeholder="Add a target role..."
                  onKeyDown={(e) => e.key === "Enter" && addRole()}
                  className="max-w-xs"
                />
                <Button variant="outline" onClick={addRole}>
                  <Plus className="h-4 w-4" />
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Search className="h-5 w-5" />
                Search Keywords
              </CardTitle>
              <CardDescription>
                Custom search queries for job discovery. These are used when the system searches for new jobs daily.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap gap-2">
                {searchKeywords.map((kw) => (
                  <Badge key={kw} variant="secondary" className="gap-1 pr-1.5 text-sm py-1">
                    {kw}
                    <button
                      onClick={() => setSearchKeywords(searchKeywords.filter((k) => k !== kw))}
                      className="ml-1 hover:text-destructive"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </Badge>
                ))}
                {searchKeywords.length === 0 && (
                  <span className="text-sm text-muted-foreground">
                    No custom keywords. Target roles will be used as search terms.
                  </span>
                )}
              </div>
              <div className="flex gap-2">
                <Input
                  value={newKeyword}
                  onChange={(e) => setNewKeyword(e.target.value)}
                  placeholder="e.g. senior product manager fintech, AI engineer remote"
                  onKeyDown={(e) => e.key === "Enter" && addKeyword()}
                  className="max-w-md"
                />
                <Button variant="outline" onClick={addKeyword}>
                  <Plus className="h-4 w-4" />
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Globe className="h-5 w-5" />
                Target Countries
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap gap-2">
                {countries.map((c) => {
                  // Show the country NAME (not just the ISO code) so a
                  // glance at the row is enough to tell "DE" from "DK".
                  const meta = COUNTRY_OPTIONS.find((o) => o.code === c);
                  return (
                    <Badge key={c} variant="outline" className="gap-1 pr-1.5 text-sm py-1">
                      {meta ? meta.name : c}
                      <button
                        onClick={() => setCountries(countries.filter((x) => x !== c))}
                        className="ml-1 hover:text-destructive"
                        aria-label={`Remove ${meta?.name ?? c}`}
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </Badge>
                  );
                })}
                {countries.length === 0 && (
                  <span className="text-sm text-muted-foreground">No countries added yet</span>
                )}
              </div>
              {/* Dropdown of real countries instead of a free-text input.
                  The old input + Plus button accepted any string (so
                  typos like "U" or "USA" got stored verbatim) and
                  often appeared broken because users didn't realise
                  it expected a 2-letter ISO code. */}
              <DropdownMenu>
                <DropdownMenuTrigger
                  render={
                    <Button variant="outline" size="sm">
                      <Plus className="h-4 w-4" />
                      Add country
                    </Button>
                  }
                />
                <DropdownMenuContent align="start" className="max-h-[320px] overflow-y-auto">
                  {(["Europe", "Americas", "Asia-Pacific", "Other"] as const).map((group, gi) => {
                    const items = COUNTRY_OPTIONS.filter((o) => o.group === group);
                    return (
                      <div key={group}>
                        {gi > 0 && <DropdownMenuSeparator />}
                        <DropdownMenuLabel className="text-xs text-muted-foreground">
                          {group}
                        </DropdownMenuLabel>
                        {items.map((opt) => {
                          const already = countries.includes(opt.code);
                          return (
                            <DropdownMenuItem
                              key={opt.code}
                              disabled={already}
                              onClick={() => {
                                if (!already) {
                                  setCountries([...countries, opt.code]);
                                }
                              }}
                              className="flex items-center justify-between gap-3"
                            >
                              <span>{opt.name}</span>
                              <span className="text-xs text-muted-foreground font-mono">
                                {already ? "added" : opt.code}
                              </span>
                            </DropdownMenuItem>
                          );
                        })}
                      </div>
                    );
                  })}
                </DropdownMenuContent>
              </DropdownMenu>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <X className="h-5 w-5" />
                Hide sources
              </CardTitle>
              <CardDescription>
                Skip jobs from boards that don&apos;t match your search. The PM
                role usually wants to hide Adzuna (US-heavy); the AI role
                usually keeps it on.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid gap-2 sm:grid-cols-2">
                {[
                  { key: "adzuna", label: "Adzuna", note: "US/UK aggregator" },
                  { key: "linkedin", label: "LinkedIn", note: "Apify-scraped" },
                  { key: "indeed", label: "Indeed", note: "Apify-scraped" },
                  { key: "google_jobs", label: "Google Jobs", note: "Apify-scraped" },
                  { key: "jsearch", label: "JSearch", note: "RapidAPI aggregator" },
                  { key: "remoteok", label: "RemoteOK", note: "Remote-only board" },
                  { key: "arbeitnow", label: "Arbeitnow", note: "Europe + visa" },
                  { key: "himalayas", label: "Himalayas", note: "Worldwide remote" },
                  { key: "remotive", label: "Remotive", note: "Remote-only board" },
                  { key: "weworkremotely", label: "WeWorkRemotely", note: "Remote-only board" },
                  { key: "crossover", label: "Crossover", note: "Crossover.com only" },
                  { key: "dailyremote", label: "DailyRemote", note: "Remote-only, scraped" },
                ].map((src) => {
                  const blocked = blockedSources.includes(src.key);
                  return (
                    <label
                      key={src.key}
                      className={`flex items-center gap-3 rounded-lg border px-3 py-2.5 cursor-pointer transition-colors ${
                        blocked
                          ? "border-red-500/20 bg-red-500/[0.03]"
                          : "border-white/[0.06] hover:border-white/[0.12]"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={blocked}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setBlockedSources([...blockedSources, src.key]);
                          } else {
                            setBlockedSources(blockedSources.filter((s) => s !== src.key));
                          }
                        }}
                        className="h-4 w-4 accent-red-500"
                      />
                      <div className="flex-1 min-w-0">
                        <p className={`text-sm font-medium ${blocked ? "line-through text-muted-foreground" : ""}`}>
                          {src.label}
                        </p>
                        <p className="text-sm text-muted-foreground">{src.note}</p>
                      </div>
                    </label>
                  );
                })}
              </div>
              {blockedSources.length > 0 && (
                <p className="text-xs text-muted-foreground mt-3">
                  Hiding {blockedSources.length} source{blockedSources.length === 1 ? "" : "s"}.
                  Save preferences below to apply.
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <DollarSign className="h-5 w-5" />
                Compensation
              </CardTitle>
            </CardHeader>
            <CardContent>
              {/* Stack Min/Max/Currency on phones (3 columns @ 375px = squashed
                  inputs); 3-up only at sm and above. */}
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 sm:gap-4">
                <div className="space-y-2">
                  <Label>Min Salary</Label>
                  <Input
                    type="number"
                    value={salaryMin}
                    onChange={(e) => setSalaryMin(e.target.value)}
                    placeholder="100000"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Max Salary</Label>
                  <Input
                    type="number"
                    value={salaryMax}
                    onChange={(e) => setSalaryMax(e.target.value)}
                    placeholder="200000"
                  />
                </div>
                <div className="space-y-2 col-span-2 sm:col-span-1">
                  <Label>Currency</Label>
                  <Input
                    value={salaryCurrency}
                    onChange={(e) => setSalaryCurrency(e.target.value)}
                    placeholder="USD"
                  />
                </div>
              </div>
              <Separator className="my-4" />
              <div className="space-y-2">
                <Label>Remote Preference</Label>
                <div className="flex flex-wrap gap-2">
                  {[
                    { label: "Any", value: "any" },
                    { label: "Remote Only", value: "full_remote" },
                    { label: "Hybrid OK", value: "hybrid" },
                    { label: "On-site OK", value: "onsite" },
                  ].map((pref) => (
                    <Button
                      key={pref.value}
                      variant={remotePref === pref.value ? "default" : "outline"}
                      onClick={() => setRemotePref(pref.value)}
                    >
                      {pref.label}
                    </Button>
                  ))}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-3 mt-4">
                <Button onClick={handleSavePreferences} disabled={isSavingProfile}>
                  {isSavingProfile ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  {isSavingProfile ? "Saving..." : "Save Preferences"}
                </Button>
                {/* One-tap rescore: useful right after correcting target_roles
                    or whenever the inbox feels off. Wipes existing scores
                    and recomputes against the current profile. */}
                <Button
                  variant="outline"
                  onClick={() => rescoreInbox.mutate()}
                  disabled={rescoreInbox.isPending}
                  title="Wipe existing scores and re-rank every job against your current profile."
                >
                  {rescoreInbox.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  {rescoreInbox.isPending ? "Re-scoring…" : "Re-score inbox"}
                </Button>
                {prefsSaved && (
                  <span className="flex items-center gap-1.5 text-sm text-emerald-400">
                    <CheckCircle2 className="h-4 w-4" /> Saved
                  </span>
                )}
                {rescoreInbox.isSuccess && (
                  <span className="flex items-center gap-1.5 text-sm text-emerald-400">
                    <CheckCircle2 className="h-4 w-4" /> Inbox refreshed
                  </span>
                )}
              </div>

              {/* Progress card — the rescore is deterministic compute
                  (~3–8 s for 1.7 k jobs) but a single spinner reads as
                  'broken or slow'. Live stage panel makes the wait feel
                  intentional. */}
              <div className="mt-4">
                <OperationProgress
                  active={rescoreInbox.isPending}
                  title="Re-scoring your inbox"
                  description="Wiping existing scores and recomputing every job against your current profile. Usually finishes in a few seconds."
                  stages={[
                    { label: "Loading your latest profile", durationMs: 800, tip: "Reading target roles, skills, work history, and preferences." },
                    { label: "Wiping old job scores", durationMs: 600, tip: "Clearing yesterday's numbers so the rerank is honest." },
                    { label: "Scoring every job in the catalogue", durationMs: 4500, tip: "Title + skill + seniority + industry + geo + remote on each row." },
                    { label: "Sorting + saving", durationMs: 1100, tip: "Updating the inbox sort order so the best matches surface first." },
                  ]}
                />
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}


/* ── Writing Samples ──────────────────────────────────────────────────────
 * Lets users paste in past cover letters / outreach messages / resume
 * summaries that the tailor service feeds Claude as style examples. Without
 * any samples, generation falls back to default behavior. Capped at 5 per
 * kind on the backend so prompt context stays bounded.
 */
const SAMPLE_KINDS: { value: "cover_letter" | "outreach" | "summary"; label: string; placeholder: string }[] = [
  {
    value: "cover_letter",
    label: "Cover letter",
    placeholder: "Paste a cover letter you've written before. We'll mimic your sentence rhythm, openers, and how you frame achievements — without copying any specific facts.",
  },
  {
    value: "outreach",
    label: "Outreach message",
    placeholder: "Paste a recruiter / hiring-manager message you've sent before. Especially useful for LinkedIn — recruiters can clock generic AI-written messages instantly.",
  },
  {
    value: "summary",
    label: "Resume summary",
    placeholder: "Paste a professional summary you've written before — the 2-3 line opener at the top of a resume.",
  },
];

function WritingSamplesCard() {
  const { data: samples, isLoading } = useSampleApplications();
  const create = useCreateSampleApplication();
  const remove = useDeleteSampleApplication();

  const [kind, setKind] = useState<"cover_letter" | "outreach" | "summary">("cover_letter");
  const [label, setLabel] = useState("");
  const [content, setContent] = useState("");
  const placeholder = SAMPLE_KINDS.find((k) => k.value === kind)?.placeholder ?? "";

  const handleSave = () => {
    if (content.trim().length < 20) return;
    create.mutate(
      { kind, label: label.trim() || null, content: content.trim() },
      {
        onSuccess: () => {
          setLabel("");
          setContent("");
        },
      },
    );
  };

  const grouped = (samples ?? []).reduce<Record<string, typeof samples>>(
    (acc, s) => {
      (acc[s.kind] ||= []).push(s);
      return acc;
    },
    {} as Record<string, typeof samples>,
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>Your writing samples</CardTitle>
        <CardDescription>
          Paste past cover letters, outreach messages, or resume summaries here.
          We read them when generating new drafts so your applications
          sound like <span className="text-foreground font-medium">you</span>,
          not generic AI. Optional — leave empty for default behavior.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {/* Add new sample */}
        <div className="space-y-3 rounded-lg border border-white/[0.06] p-4">
          <div className="flex flex-wrap gap-2">
            {SAMPLE_KINDS.map((k) => (
              <Button
                key={k.value}
                size="sm"
                variant={kind === k.value ? "default" : "outline"}
                onClick={() => setKind(k.value)}
              >
                {k.label}
              </Button>
            ))}
          </div>
          <Input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Optional label (e.g. 'AI Engineer @ Acme — landed interview')"
            className="text-sm"
          />
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder={placeholder}
            spellCheck
            className="block w-full min-h-[180px] resize-y rounded-lg bg-white/[0.02] border border-white/[0.04] focus:border-amber-500/30 focus:outline-none p-3 text-sm leading-relaxed font-sans whitespace-pre-line transition-colors"
          />
          <div className="flex items-center gap-3">
            <Button
              size="sm"
              onClick={handleSave}
              disabled={create.isPending || content.trim().length < 20}
            >
              {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {create.isPending ? "Saving…" : "Save sample"}
            </Button>
            <span className="text-xs text-muted-foreground">
              {content.trim().length < 20
                ? `${20 - content.trim().length} more chars`
                : `${content.trim().length} chars`}
            </span>
          </div>
        </div>

        {/* List existing samples grouped by kind */}
        {isLoading ? (
          <div className="flex justify-center py-4">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : !samples || samples.length === 0 ? (
          <EmptyState
            icon={Quote}
            title="No samples yet"
            description="Drafts use a generic voice by default. Paste 1–2 of your past cover letters or outreach messages above so future drafts match your style."
          />
        ) : (
          <div className="space-y-4">
            {SAMPLE_KINDS.map((k) => {
              const items = grouped[k.value] || [];
              if (items.length === 0) return null;
              return (
                <div key={k.value} className="space-y-2">
                  <p className="text-xs uppercase tracking-wider text-muted-foreground">
                    {k.label} <span className="text-muted-foreground/60">({items.length}/5)</span>
                  </p>
                  {items.map((s) => (
                    <div
                      key={s.id}
                      className="rounded-lg border border-white/[0.06] p-3 space-y-2"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <p className="text-sm font-medium leading-snug">
                          {s.label || <span className="text-muted-foreground italic">Untitled</span>}
                        </p>
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          onClick={() => remove.mutate(s.id)}
                          title="Delete sample"
                        >
                          <Trash2 className="h-4 w-4 text-muted-foreground hover:text-destructive" />
                        </Button>
                      </div>
                      <p className="text-xs text-muted-foreground leading-relaxed line-clamp-3 whitespace-pre-line">
                        {s.content}
                      </p>
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
