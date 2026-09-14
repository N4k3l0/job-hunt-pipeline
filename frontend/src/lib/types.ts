// Job types
export interface Job {
  id: string;
  company: string;
  title: string;
  /** English translation of `title` when the source posting wasn't
   *  English. NULL on already-English jobs — render as `title_en ||
   *  title` so the display is always English when the translator caught it. */
  title_en?: string | null;
  location: string | null;
  country: string | null;
  remote_type: string | null;
  job_url: string | null;
  apply_url: string | null;
  salary_text: string | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  employment_type: string | null;
  seniority: string | null;
  application_type: string | null;
  source_name: string | null;
  status: string;
  discovered_at: string;
  /** Last time a job board listed this job (it was still open then). */
  last_seen_at?: string | null;
  /** Last time the job's link was checked. */
  last_checked_at?: string | null;
  expires_at: string | null;
}

export interface JobDetail extends Job {
  raw_description: string | null;
  entities: JobEntity | null;
  score: JobScore | null;
  auto_apply?: {
    /** The job's form is on Greenhouse, Lever or Ashby. */
    supported: boolean;
    application_id: string | null;
    status: AutoApplicationStatus | null;
  };
}

// ── Apply for me ──────────────────────────────────────────────────────────

export type AutoApplicationStatus =
  | "preparing"
  | "needs_you"
  | "queued"
  | "submitting"
  | "submitted"
  | "failed"
  | "unsupported"
  | "cancelled";

export type AutoApplyValue = string | number | boolean | string[] | null;

export interface AutoApplyAnswer {
  value: AutoApplyValue;
  /** profile | saved | default | suggested | drafted | user */
  source: string | null;
  confirmed: boolean;
  note: string | null;
}

export interface AutoApplyField {
  key: string;
  label: string;
  type:
    | "text" | "textarea" | "email" | "phone" | "url" | "number" | "date"
    | "file" | "select" | "multiselect" | "boolean" | "location";
  required: boolean;
  options: { label: string; value: string }[] | null;
  description: string | null;
  group: "application" | "voluntary";
  kind: string;
  answer: AutoApplyAnswer | null;
  needs_attention: boolean;
}

export interface AutoApplication {
  id: string;
  job_id: string;
  job: { id: string; title: string; company: string; location: string | null } | null;
  status: AutoApplicationStatus;
  ats: "greenhouse" | "lever" | "ashby" | null;
  form_url: string | null;
  open_count: number;
  error: string | null;
  submitted_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface AutoApplicationDetail extends AutoApplication {
  fields: AutoApplyField[];
  result: Record<string, unknown> | null;
}

export interface JobEntity {
  skills: string[] | null;
  requirements: string[] | null;
  keywords: string[] | null;
  nice_to_have: string[] | null;
  visa_notes: string | null;
  sponsorship_available: boolean | null;
  application_questions: string[] | null;
  years_experience_min: number | null;
  years_experience_max: number | null;
}

export interface JobScore {
  role_path: string;
  title_score: number;
  skill_score: number;
  seniority_score: number;
  industry_score: number;
  geo_score: number;
  remote_score: number;
  salary_score: number;
  visa_score: number;
  overall_fit: number;
  priority: string;
  reasoning: Record<string, string> | null;
  calculated_at: string;
  deep_score: {
    overall_fit_score: number;
    strengths: string[];
    gaps: string[];
    experience_relevance: string;
    relevant_roles: string[];
    recommendation: string;
    summary: string;
    scored_at: string;
    model: string;
  } | null;
}

export interface JobListResponse {
  jobs: Job[];
  total: number;
  page: number;
  page_size: number;
}

// Candidate types
export interface CandidateProfile {
  id: string;
  user_id: string;
  headline: string | null;
  master_summary: string | null;
  target_roles: string[] | null;
  preferred_countries: string[] | null;
  /** ISO-2 code of where the candidate lives; hides remote jobs they aren't eligible for. */
  home_country: string | null;
  visa_statuses: Record<string, string> | null;
  remote_preference: string | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string;
  blocked_sources: string[] | null;
  search_keywords: string[] | null;
  links: Record<string, string> | null;
  phone: string | null;
  current_location: string | null;
}

export interface Resume {
  id: string;
  version_name: string;
  tags: string[] | null;
  source_type: string;
  file_url: string;
  parsed_at: string | null;
  created_at: string;
}

export interface Bullet {
  id: string;
  text: string;
  domain_tags: string[] | null;
  role_tags: string[] | null;
  keywords: string[] | null;
  used_count: number;
}

// Tailoring types
export type ApprovalStatus = "pending" | "generating" | "ready" | "approved" | "rejected" | "failed";

export interface TailoredApplication {
  id: string;
  job_id: string;
  tailored_summary: string | null;
  cover_letter: string | null;
  recruiter_message: string | null;
  short_answers: Record<string, string> | null;
  keyword_matches: {
    matched: string[];
    unmatched: string[];
  } | null;
  validation_notes: Record<string, string[]> | null;
  approval_status: ApprovalStatus;
  progress_step: string | null;
  tailored_resume_url: string | null;
  created_at: string;
  updated_at: string;
  job?: Job;
}

// Tracking types
export interface ApplicationTracking {
  id: string;
  job_id: string;
  status: string;
  applied_at: string | null;
  follow_up_date: string | null;
  notes: string | null;
  created_at: string;
  job?: Job;
}

// Analytics types
export interface AnalyticsOverview {
  jobs_discovered: number;
  jobs_shortlisted: number;
  applications_sent: number;
  response_rate: number;
  interview_rate: number;
  applications_this_week: number;
  /** ISO timestamp of the most recent job discovery sweep, used by the
   *  dashboard greeting hint to be honest about cron freshness. */
  last_discovery_at: string | null;
}
