import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import type {
  Job,
  JobDetail,
  JobListResponse,
  CandidateProfile,
  Resume,
  Bullet,
  TailoredApplication,
  ApplicationTracking,
  AnalyticsOverview,
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

export function useUsers() {
  return useQuery({
    queryKey: ["auth", "users"],
    queryFn: () => api.get<{ id: string; email: string; name: string; role: string }[]>("/api/v1/auth/users"),
    staleTime: 10 * 60 * 1000,
  });
}

export function useInviteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (email: string) => api.post("/api/v1/auth/invite", { email }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["auth", "users"] }),
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
    queryFn: () => api.get<any[]>("/api/v1/candidates/work-history"),
    staleTime: 5 * 60 * 1000,
  });
}

export function useSkills() {
  return useQuery({
    queryKey: ["skills"],
    queryFn: () => api.get<any[]>("/api/v1/candidates/skills"),
    staleTime: 5 * 60 * 1000,
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
    onSuccess: () => qc.invalidateQueries({ queryKey: ["resumes"] }),
  });
}

export function useDeleteResume() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/api/v1/candidates/resumes/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["resumes"] }),
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

export function useAddBullet() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<Bullet>) => api.post("/api/v1/candidates/bullet-bank", data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bullets"] }),
  });
}

// ── Jobs ─────────────────────────────────────────────────────────────────────

export function useJobs(params: {
  page?: number;
  pageSize?: number;
  roleType?: string | null;
  country?: string | null;
  remoteOnly?: boolean;
  remoteType?: string | null;
  sponsorship?: boolean;
  source?: string | null;
  minScore?: number | null;
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
  if (params.minScore) searchParams.set("min_score", String(params.minScore));
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

export function useDismissJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => api.post(`/api/v1/jobs/${jobId}/dismiss`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });
}

// ── Scoring ──────────────────────────────────────────────────────────────────

export function useScoreJob() {
  return useMutation({
    mutationFn: (jobId: string) => api.post(`/api/v1/scoring/run/${jobId}`),
  });
}

export function useBatchScore() {
  return useMutation({
    mutationFn: () => api.post("/api/v1/scoring/batch"),
  });
}

// ── Tailoring ────────────────────────────────────────────────────────────────

export function useDeepScore() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => api.post<{ deep_score: any }>(`/api/v1/jobs/${jobId}/deep-score`),
    onSuccess: (_data, jobId) => qc.invalidateQueries({ queryKey: ["job", jobId] }),
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
  });
}

export function useTailoredApplication(id: string) {
  return useQuery({
    queryKey: ["tailoring", id],
    queryFn: () => api.get<TailoredApplication>(`/api/v1/tailoring/${id}`),
    enabled: !!id,
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

export function useApproveTailored() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post(`/api/v1/tailoring/${id}/approve`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tailoring"] });
      qc.invalidateQueries({ queryKey: ["tracking"] });
    },
  });
}

export function useDeleteTailored() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/api/v1/tailoring/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tailoring"] }),
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
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tracking"] }),
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
