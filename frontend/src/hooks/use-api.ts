import { keepPreviousData, useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import type {
  JobDetail,
  JobListResponse,
  CandidateProfile,
  Resume,
  Bullet,
  TailoredApplication,
  ApplicationTracking,
  AnalyticsOverview,
  AutoApplication,
  AutoApplicationDetail,
  AutoApplyValue,
  JobAlertStatus,
  Skill,
  SkillCategory,
  WorkHistoryEntry,
  JobRatingValue,
  RatingCounts,
  RatingQueue,
  RatingResults,
} from "@/lib/types";

// ── Auth ─────────────────────────────────────────────────────────────────────

export function useCurrentUser() {
  return useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => api.get<{ id: string; email: string; name: string; role: string }>("/api/v1/auth/me"),
    retry: false,
    staleTime: 10 * 60 * 1000,
  });
}

export function useRunDiscovery() {
  const qc = useQueryClient();
  return useMutation<{
    status: string;
    results: Record<string, string>;
    scoring: Record<string, string>;
  }>({
    mutationFn: () => api.post("/api/v1/auth/admin/run-discovery"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["analytics"] });
    },
  });
}

export function useStaleJobsPreview(days = 30) {
  return useQuery({
    queryKey: ["admin", "stale-jobs", days],
    queryFn: () =>
      api.get<{ would_expire: number; total_unapplied: number; days: number }>(
        `/api/v1/auth/admin/stale-jobs/preview?days=${days}`,
      ),
    staleTime: 60 * 1000,
  });
}

export function useStaleJobsCleanup() {
  const qc = useQueryClient();
  return useMutation<{ expired: number; days: number }, Error, { days?: number }>({
    mutationFn: ({ days = 30 } = {}) =>
      api.post(`/api/v1/auth/admin/stale-jobs/cleanup?days=${days}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["analytics"] });
      qc.invalidateQueries({ queryKey: ["admin", "stale-jobs"] });
    },
  });
}

export interface StaleVerifyBatch {
  checked: number;
  expired: number;
  alive: number;
  ambiguous: number;
  skipped?: number;
  has_more: boolean;
}

export interface EmbeddingsBackfillBatch {
  embedded: number;
  remaining: number;
  has_more: boolean;
}

export function useStaleJobsVerifyBatch() {
  const qc = useQueryClient();
  return useMutation<StaleVerifyBatch, Error, { limit?: number; ageDaysMin?: number }>({
    mutationFn: ({ limit = 100, ageDaysMin = 0 } = {}) =>
      api.post(
        `/api/v1/auth/admin/stale-jobs/verify?limit=${limit}&age_days_min=${ageDaysMin}`,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["analytics"] });
      qc.invalidateQueries({ queryKey: ["admin", "stale-jobs"] });
    },
  });
}

export interface VerifyDebugReport {
  checked: number;
  by_outcome: Record<string, number>;
  by_host: { host: string; total: number; by_outcome: Record<string, number> }[];
  samples: { url: string; host: string; outcome: string; company: string; title: string | null }[];
}

export function useStaleJobsVerifyDebug() {
  return useMutation<VerifyDebugReport, Error, { limit?: number }>({
    mutationFn: ({ limit = 50 } = {}) =>
      api.get(`/api/v1/auth/admin/stale-jobs/verify-debug?limit=${limit}`),
  });
}

export function useUpdateMe() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      api.patch<{ id: string; email: string; name: string; role: string }>(
        "/api/v1/auth/me",
        { name },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["auth", "me"] }),
  });
}

// ── Profile ──────────────────────────────────────────────────────────────────

export function useProfile() {
  return useQuery({
    queryKey: ["profile"],
    queryFn: () => api.get<CandidateProfile | null>("/api/v1/candidates/profile"),
    staleTime: 5 * 60 * 1000,
  });
}

export function useCreateProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<CandidateProfile>) => api.post("/api/v1/candidates/profile", data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["profile"] }),
  });
}

export function useUpdateProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<CandidateProfile>) => api.put("/api/v1/candidates/profile", data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["profile"] }),
  });
}

// ── Work History & Skills ────────────────────────────────────────────────────

export function useWorkHistory() {
  return useQuery({
    queryKey: ["work-history"],
    queryFn: () => api.get<WorkHistoryEntry[]>("/api/v1/candidates/work-history"),
    staleTime: 5 * 60 * 1000,
  });
}

export type WorkHistoryInput = {
  company: string;
  title: string;
  start_date: string | null;
  end_date: string | null;
  bullets: string[];
};

/** Adds a role, or changes one when `id` is given. */
export function useSaveWorkHistory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id?: string; data: WorkHistoryInput }) =>
      id
        ? api.put<WorkHistoryEntry>(`/api/v1/candidates/work-history/${id}`, data)
        : api.post<WorkHistoryEntry>("/api/v1/candidates/work-history", data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["work-history"] }),
  });
}

export function useDeleteWorkHistory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/api/v1/candidates/work-history/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["work-history"] }),
  });
}

export function useSkills() {
  return useQuery({
    queryKey: ["skills"],
    queryFn: () => api.get<Skill[]>("/api/v1/candidates/skills"),
    staleTime: 5 * 60 * 1000,
  });
}

export function useAddSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { skill_name: string; category: SkillCategory }) =>
      api.post<Skill>("/api/v1/candidates/skills", data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["skills"] }),
  });
}

export function useDeleteSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/api/v1/candidates/skills/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["skills"] }),
  });
}

// ── Resumes ──────────────────────────────────────────────────────────────────

export function useResumes() {
  return useQuery({
    queryKey: ["resumes"],
    queryFn: () => api.get<Resume[]>("/api/v1/candidates/resumes"),
    staleTime: 5 * 60 * 1000,
  });
}

export function useUploadResume() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ file, versionName, tags }: { file: File; versionName: string; tags: string }) =>
      api.upload<Resume>("/api/v1/candidates/resumes", file, { version_name: versionName, tags }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["resumes"] });
      qc.invalidateQueries({ queryKey: ["profile"] });
      // Rescoring runs as its own request: parsing plus a full rescore in
      // one request can exceed the backend's 60s limit.
      api
        .post("/api/v1/candidates/rescore")
        .then(() => {
          qc.invalidateQueries({ queryKey: ["jobs"] });
          qc.invalidateQueries({ queryKey: ["analytics"] });
        })
        .catch(() => {
          // Scores refresh on the next scheduled pass if this fails.
        });
    },
  });
}

export interface SampleApplication {
  id: string;
  kind: "cover_letter" | "outreach" | "summary";
  label: string | null;
  content: string;
  created_at: string | null;
}

export function useSampleApplications() {
  return useQuery({
    queryKey: ["sample-applications"],
    queryFn: () => api.get<SampleApplication[]>("/api/v1/candidates/sample-applications"),
    staleTime: 5 * 60 * 1000,
  });
}

export function useCreateSampleApplication() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { kind: string; label: string | null; content: string }) =>
      api.post<SampleApplication>("/api/v1/candidates/sample-applications", data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sample-applications"] }),
  });
}

export function useDeleteSampleApplication() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.delete(`/api/v1/candidates/sample-applications/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sample-applications"] }),
  });
}

export function useDeleteResume() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/api/v1/candidates/resumes/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["resumes"] }),
  });
}

export function useAutoSuggestRoles() {
  const qc = useQueryClient();
  return useMutation<{
    suggested: string[];
    applied: boolean;
    reason: string;
  }>({
    mutationFn: () => api.post("/api/v1/candidates/auto-suggest-roles"),
    onSuccess: (data) => {
      if (data.applied) {
        qc.invalidateQueries({ queryKey: ["jobs"] });
        qc.invalidateQueries({ queryKey: ["analytics"] });
        qc.invalidateQueries({ queryKey: ["profile"] });
      }
    },
  });
}

export function useRescoreInbox() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post("/api/v1/candidates/rescore"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["analytics"] });
    },
  });
}

export interface JobContact {
  name: string | null;
  title: string | null;
  linkedin_url: string | null;
  email_guess: string | null;
  confidence: "low" | "medium" | "high" | null;
  source_notes: string | null;
  citations: { url: string; title: string }[];
  searched_at: string | null;
  cached: boolean;
}

export function useJobContact(jobId: string | undefined) {
  return useQuery({
    queryKey: ["jobs", jobId, "contact"],
    queryFn: () =>
      api.get<{ contact: JobContact | null }>(`/api/v1/jobs/${jobId}/contact`),
    enabled: !!jobId,
    // Cached server-side too — no need to re-fetch aggressively.
    staleTime: 30 * 60 * 1000,
  });
}

export interface TailoredBullet {
  id: string;
  original: string;
  tailored: string;
  relevance: number; // 0-5; 0 = LLM didn't rank it
  why_it_matches: string;
}

export interface BulkUrlImportResult {
  found: number;
  processed: number;
  imported: number;
  failed: number;
  deferred: number;
  results: { url: string; status: "ok" | "failed"; error?: string }[];
  has_more: boolean;
  remaining_urls: string[];
}

export function useImportBulkUrls() {
  const qc = useQueryClient();
  return useMutation<BulkUrlImportResult, Error, { text: string; source?: string }>({
    mutationFn: ({ text, source = "linkedin_alert" }) =>
      api.post("/api/v1/jobs/import/bulk-urls", { text, source }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["analytics"] });
    },
  });
}

export function useTailorBullets(jobId: string | undefined) {
  return useMutation<{ bullets: TailoredBullet[]; job_id: string }>({
    mutationFn: () => api.post(`/api/v1/jobs/${jobId}/tailor-bullets`),
  });
}

export interface WebSearchResult {
  found: number;
  ingested: number;
  duplicates: number;
  scored: number;
}

export function useFindMoreJobs() {
  const qc = useQueryClient();
  return useMutation<WebSearchResult>({
    mutationFn: () => api.post("/api/v1/jobs/search-web"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["analytics"] });
    },
  });
}

export function useFindJobContact(jobId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ force = false }: { force?: boolean } = {}) =>
      api.post<{ contact: JobContact }>(
        `/api/v1/jobs/${jobId}/find-contact${force ? "?force=true" : ""}`,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs", jobId, "contact"] });
    },
  });
}

// ── Bullets ──────────────────────────────────────────────────────────────────

export function useBullets() {
  return useQuery({
    queryKey: ["bullets"],
    queryFn: () => api.get<Bullet[]>("/api/v1/candidates/bullet-bank"),
    staleTime: 5 * 60 * 1000,
  });
}

// ── Jobs ─────────────────────────────────────────────────────────────────────

export function useJobs(params: {
  page?: number;
  pageSize?: number;
  roleType?: string | null;
  /** Single ISO-2 code OR comma-separated list (e.g. "US" or "NL,DE,FR"). */
  country?: string | null;
  remoteOnly?: boolean;
  remoteType?: string | null;
  sponsorship?: boolean;
  source?: string | null;
  minScore?: number | null;
  /** Per-user job status filter (e.g. "shortlisted"). */
  status?: string | null;
  /** Recent-window filter as "Nh" / "Nd" / "Nw" (e.g. "24h", "7d"). */
  since?: string | null;
  sortBy?: string;
} = {}) {
  const searchParams = new URLSearchParams();
  if (params.page) searchParams.set("page", String(params.page));
  if (params.pageSize) searchParams.set("page_size", String(params.pageSize));
  if (params.roleType) searchParams.set("role_type", params.roleType);
  if (params.country) searchParams.set("country", params.country);
  if (params.remoteType) searchParams.set("remote_type", params.remoteType);
  else if (params.remoteOnly) searchParams.set("remote_only", "true");
  if (params.sponsorship) searchParams.set("sponsorship", "true");
  if (params.source) searchParams.set("source", params.source);
  if (params.minScore != null) searchParams.set("min_score", String(params.minScore));
  if (params.status) searchParams.set("status", params.status);
  if (params.since) searchParams.set("since", params.since);
  if (params.sortBy) searchParams.set("sort_by", params.sortBy);

  const qs = searchParams.toString();
  return useQuery({
    queryKey: ["jobs", params],
    queryFn: () => api.get<JobListResponse>(`/api/v1/jobs${qs ? `?${qs}` : ""}`),
    staleTime: 2 * 60 * 1000,
  });
}

export function useJob(jobId: string) {
  return useQuery({
    queryKey: ["jobs", jobId],
    queryFn: () => api.get<JobDetail>(`/api/v1/jobs/${jobId}`),
    enabled: !!jobId,
  });
}

export function useImportJobUrl() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (url: string) => api.post("/api/v1/jobs/import/url", { url }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });
}

export function useImportJobText() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ text, source }: { text: string; source: string }) =>
      api.post("/api/v1/jobs/import/text", { text, source }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });
}

export function useShortlistJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => api.post(`/api/v1/jobs/${jobId}/shortlist`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });
}

// ── Scoring ──────────────────────────────────────────────────────────────────

// ── Tailoring ────────────────────────────────────────────────────────────────

export function useDeepScore() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => api.post<{ deep_score: any }>(`/api/v1/jobs/${jobId}/deep-score`),
    // useJob caches under ["jobs", jobId] (plural); the previous
    // ["job", jobId] key never matched, so the UI didn't refetch and
    // the new deep_score never showed up despite the server saving it.
    onSuccess: (_data, jobId) => qc.invalidateQueries({ queryKey: ["jobs", jobId] }),
  });
}

export function useGenerateTailored() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => api.post(`/api/v1/tailoring/generate/${jobId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tailoring"] }),
  });
}

export function useReviewQueue() {
  return useQuery({
    queryKey: ["tailoring", "queue"],
    queryFn: () => api.get<TailoredApplication[]>("/api/v1/tailoring/queue"),
    staleTime: 2 * 60 * 1000,
    // Poll while a tailoring task is in flight so the UI shows live progress
    // without the user having to refresh.
    refetchInterval: (query) => {
      const data = query.state.data as TailoredApplication[] | undefined;
      return data?.some((t) => t.approval_status === "generating") ? 2500 : false;
    },
  });
}

export function useTailoredApplication(id: string) {
  return useQuery({
    queryKey: ["tailoring", id],
    queryFn: () => api.get<TailoredApplication>(`/api/v1/tailoring/${id}`),
    enabled: !!id,
  });
}

export type RegeneratableSection = "tailored_summary" | "cover_letter" | "recruiter_message";

export function useRegenerateSection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, section, guidance }: { id: string; section: RegeneratableSection; guidance?: string }) =>
      api.post<{ section: RegeneratableSection; content: string }>(
        `/api/v1/tailoring/${id}/regenerate-section`,
        { section, guidance: guidance || null },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tailoring"] }),
  });
}

export function useUpdateTailored() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<TailoredApplication> }) =>
      api.put(`/api/v1/tailoring/${id}`, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tailoring"] }),
  });
}

export interface ApproveResponse {
  id: string;
  job_id: string;
  approval_status: string;
  approved_at: string | null;
  tracking_id: string;
}

export function useApproveTailored() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<ApproveResponse>(`/api/v1/tailoring/${id}/approve`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tailoring"] });
      qc.invalidateQueries({ queryKey: ["tracking"] });
      // Approve creates an application_tracking row — the inbox filter
      // hides jobs that have one, so the inbox + dashboard need to refetch.
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["analytics"] });
    },
  });
}

// ── Apply for me ─────────────────────────────────────────────────────────────

export function useAutoApplications() {
  return useQuery({
    queryKey: ["auto-apply"],
    queryFn: () => api.get<AutoApplication[]>("/api/v1/auto-apply"),
    staleTime: 30 * 1000,
  });
}

export function useAutoApplication(id: string) {
  return useQuery({
    queryKey: ["auto-apply", id],
    queryFn: () => api.get<AutoApplicationDetail>(`/api/v1/auto-apply/${id}`),
    enabled: !!id,
  });
}

/** Reads the job's form and fills in answers; can take ~30s when some
 *  answers are drafted. */
export function usePrepareAutoApplication() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => api.post<AutoApplicationDetail>(`/api/v1/auto-apply/jobs/${jobId}`),
    onSuccess: (data) => {
      qc.setQueryData(["auto-apply", data.id], data);
      qc.invalidateQueries({ queryKey: ["auto-apply"], exact: true });
      qc.invalidateQueries({ queryKey: ["jobs", data.job_id] });
    },
  });
}

export function useSaveAutoApplyAnswers(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { answers: Record<string, AutoApplyValue>; approve: boolean }) =>
      api.put<AutoApplicationDetail>(`/api/v1/auto-apply/${id}/answers`, body),
    onSuccess: (data) => {
      qc.setQueryData(["auto-apply", id], data);
      qc.invalidateQueries({ queryKey: ["auto-apply"], exact: true });
      qc.invalidateQueries({ queryKey: ["jobs", data.job_id] });
      qc.invalidateQueries({ queryKey: ["profile"] });
    },
  });
}

export function useCancelAutoApplication(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<AutoApplication>(`/api/v1/auto-apply/${id}/cancel`),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["auto-apply"] });
      qc.invalidateQueries({ queryKey: ["jobs", data.job_id] });
    },
  });
}

// ── Rate matches ─────────────────────────────────────────────────────────────

/** Jobs to rate, best-guess order fixed by the server. `limit` grows with
 *  the jobs skipped this visit, so skipped ones don't use up the page. */
export function useRatingQueue(limit: number) {
  return useQuery({
    queryKey: ["ratings", "queue", limit],
    queryFn: () => api.get<RatingQueue>(`/api/v1/ratings/queue?limit=${limit}`),
    placeholderData: keepPreviousData,
    staleTime: 0,
  });
}

export function useRatingResults(enabled: boolean) {
  return useQuery({
    queryKey: ["ratings", "results"],
    queryFn: () => api.get<RatingResults>("/api/v1/ratings/results"),
    enabled,
  });
}

export function useRateJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, rating }: { jobId: string; rating: JobRatingValue }) =>
      api.put<RatingCounts & { job_id: string; rating: JobRatingValue }>(`/api/v1/ratings/${jobId}`, { rating }),
    onSuccess: ({ rated, good }) => {
      qc.setQueriesData<RatingQueue>({ queryKey: ["ratings", "queue"] }, (old) => (old ? { ...old, rated, good } : old));
      qc.invalidateQueries({ queryKey: ["ratings", "results"] });
    },
  });
}

export function useUnrateJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => api.delete(`/api/v1/ratings/${jobId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ratings"] }),
  });
}

// ── LinkedIn job alert sync ─────────────────────────────────────────────────

export function useJobAlertStatus() {
  return useQuery({
    queryKey: ["job-alerts", "status"],
    queryFn: () => api.get<JobAlertStatus>("/api/v1/job-alerts/status"),
    staleTime: 60 * 1000,
  });
}

/** A new key for the Gmail script. The old key, if any, stops working. */
export function useCreateJobAlertKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ key: string }>("/api/v1/job-alerts/key"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job-alerts"] }),
  });
}

export function useDeleteJobAlertKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.delete("/api/v1/job-alerts/key"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job-alerts"] }),
  });
}

// ── Tracking ─────────────────────────────────────────────────────────────────

export function useApplicationPipeline() {
  return useQuery({
    queryKey: ["tracking"],
    queryFn: () => api.get<ApplicationTracking[]>("/api/v1/tracking"),
    staleTime: 2 * 60 * 1000,
  });
}

export function useUpdateStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status, notes, followUpDate }: {
      id: string; status: string; notes?: string; followUpDate?: string;
    }) => api.put(`/api/v1/tracking/${id}/status`, {
      status, notes, follow_up_date: followUpDate,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tracking"] });
      // Status transitions in/out of applied/interviewing/offered/etc.
      // change inbox visibility — refresh so the inbox + dashboard agree.
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["analytics"] });
    },
  });
}

export function useReminders() {
  return useQuery({
    queryKey: ["tracking", "reminders"],
    queryFn: () => api.get<ApplicationTracking[]>("/api/v1/tracking/reminders"),
    staleTime: 5 * 60 * 1000,
  });
}

// ── Analytics ────────────────────────────────────────────────────────────────

export function useAnalytics() {
  return useQuery({
    queryKey: ["analytics"],
    queryFn: () => api.get<AnalyticsOverview & { review_queue: number }>("/api/v1/analytics/overview"),
    staleTime: 5 * 60 * 1000,
  });
}


// ── Feedback ────────────────────────────────────────────────────────────────

export interface FeedbackPayload {
  category: "bug" | "feature" | "general";
  message: string;
  context?: string;
}

export interface FeedbackRow {
  id: string;
  user_id: string;
  user_name: string | null;
  user_email: string | null;
  category: string;
  message: string;
  context: string | null;
  resolved: boolean;
  created_at: string;
}

export function useSubmitFeedback() {
  return useMutation({
    mutationFn: (body: FeedbackPayload) =>
      api.post<{ id: string; status: string }>("/api/v1/feedback", body),
  });
}

