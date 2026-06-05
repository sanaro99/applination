export type RunStatus =
  | "queued"
  | "running"
  | "done"
  | "error"
  | "cancelled";

export type ApplicationStatus =
  | "generated"
  | "applied"
  | "interviewing"
  | "rejected"
  | "offer"
  | "archived";

export interface Run {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: RunStatus;
  dry_run: boolean;
  no_pdf: boolean;
  no_cache: boolean;
  jobs_found: number;
  applications_created: number;
  day_root: string | null;
  error: string | null;
}

export interface Application {
  id: number;
  run_id: number | null;
  company: string;
  title: string;
  location: string;
  url: string;
  source: string;
  match_score: number;
  match_reason: string;
  folder_rel: string;
  resume_file: string;
  cover_file: string;
  answers_file: string;
  status: ApplicationStatus;
  notes: string;
  tags: string[];
  applied_at: string | null;
  deadline: string | null;
  created_at: string;
}

export type PipelineEvent =
  | { type: "stage_started"; stage: string; total?: number }
  | {
      type: "stage_completed";
      stage: string;
      duration_s?: number;
      jobs_found?: number;
      kept?: number;
      top?: RankedJobPreview[];
      applications?: number;
      tracker_file?: string;
    }
  | {
      type: "job_started";
      idx: number;
      total: number;
      company: string;
      title: string;
      score: number;
      source: string;
      url: string;
      location: string;
    }
  | {
      type: "job_completed";
      idx: number;
      total: number;
      company: string;
      title: string;
      score: number;
      folder: string;
      folder_rel: string;
      resume_file: string;
      cover_file: string;
      answers_file: string;
      error: string;
    }
  | {
      type: "job_cached";
      idx: number;
      total: number;
      company: string;
      title: string;
      score: number;
      resume_file: string;
      cover_file: string;
    }
  | { type: "log"; level: string; name: string; msg: string }
  | { type: "rank_pool"; jobs: unknown[] }
  | {
      type: "done";
      applications: number;
      jobs_found: number;
      day_root: string;
      dry_run: boolean;
    }
  | { type: "stopping"; graceful: boolean }
  | {
      type: "cancelled";
      graceful: boolean;
      applications: number;
      jobs_found: number;
      day_root: string;
      dry_run: boolean;
    }
  | { type: "error"; msg: string };

export interface StatsResponse {
  total_applications: number;
  avg_score: number;
  runs_total: number;
  runs_30d: number;
  by_status: Record<string, number>;
  by_source: Record<string, number>;
  top_companies: { company: string; count: number }[];
  daily: { date: string; count: number }[];
  score_buckets: { bucket: string; count: number }[];
}

export interface ResumeVersion {
  version: number;
  docx: string;
  pdf: string | null;
  json: string | null;
}

export interface ProviderInfo {
  name: string;
  model: string;
  configured: boolean;
  role: "primary" | "fallback" | "available";
}

export interface TaskRouting {
  primary: string | null;
  fallbacks: string[];
  models: Record<string, string>;
}

export interface LlmConfig {
  task_names: string[];
  global: { primary: string | null; fallbacks: string[] };
  providers: ProviderInfo[];
  tasks: Record<string, TaskRouting>;
}

export interface GeneratedStory {
  filename: string;
  text: string;
  fields: Record<string, unknown>;
}

export interface ProviderTestResult {
  ok: boolean;
  provider: string;
  model: string;
  latency_ms: number;
  sample: string;
  error: string;
}

export interface RunCompareSummary {
  id: number;
  status: string;
  started_at: string | null;
  duration_s: number | null;
  jobs_found: number;
  applications_created: number;
  avg_score: number;
  by_status: Record<string, number>;
  companies: string[];
}

export interface RunCompare {
  a: RunCompareSummary;
  b: RunCompareSummary;
  shared_companies: string[];
  only_a: string[];
  only_b: string[];
}

export interface RankedJob {
  id: number;
  run_id: number;
  company: string;
  title: string;
  location: string;
  url: string;
  source: string;
  remote: boolean;
  match_score: number;
  match_reason: string;
  selected: boolean;
  dismissed: boolean;
  application_id: number | null;
}

export interface RankedJobPreview {
  company: string;
  title: string;
  location: string;
  score: number;
  reason: string;
  source: string;
  url: string;
}

export interface InboxStatus {
  configured: boolean;
  enabled: boolean;
  email_masked: string;
  scan_days: number;
  last_sync: string | null;
  auto_update_status: boolean;
}

export interface InboxSyncUpdate {
  application_id: number;
  company: string;
  title: string;
  from_email: string;
  category: string;
  confidence: number;
  old_status: string;
  new_status: string;
  summary: string;
}

export interface InboxSyncResult {
  scanned: number;
  matched: number;
  classified: number;
  updates: InboxSyncUpdate[];
  skipped_low_confidence: number;
  error?: string | null;
}

export interface DigestPreview {
  subject: string;
  html: string;
  text: string;
  empty: boolean;
}

export interface RemindersStatus {
  can_send_email: boolean;
  digest_enabled: boolean;
  counts: {
    deadlines: number;
    interviews: number;
    follow_ups: number;
    new_matches: number;
  };
}

export type ChatMode = "chat" | "interview";

export interface ChatSession {
  id: number;
  title: string;
  mode: ChatMode;
  application_id: number | null;
  application_label: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface ChatSessionDetail {
  session: ChatSession;
  messages: ChatMessage[];
}

export interface PostMessageResult {
  user_message: ChatMessage;
  assistant_message: ChatMessage;
}

export interface SavedAnswer {
  id: number;
  title: string;
  prompt: string;
  content: string;
  tags: string[];
  application_id: number | null;
  created_at: string;
}
