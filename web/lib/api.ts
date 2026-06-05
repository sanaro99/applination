import type {
  Application,
  ApplicationStatus,
  ChatMessage,
  ChatMode,
  ChatSession,
  ChatSessionDetail,
  DigestPreview,
  GeneratedStory,
  InboxStatus,
  InboxSyncResult,
  LlmConfig,
  PipelineEvent,
  PostMessageResult,
  ProviderInfo,
  ProviderTestResult,
  RankedJob,
  RemindersStatus,
  ResumeVersion,
  Run,
  RunCompare,
  SavedAnswer,
  StatsResponse,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export type OnboardingStatus = {
  onboarded: boolean;
  marked_complete: boolean;
  can_run: boolean;
  steps: {
    provider: boolean;
    contact: boolean;
    resume: boolean;
    bio: boolean;
    stories: number;
  };
};

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = "";
    try {
      detail = await res.text();
    } catch {}
    throw new Error(`${res.status} ${res.statusText}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => http<{ ok: boolean }>("/api/health"),

  startRun: (body: {
    dry_run?: boolean;
    no_pdf?: boolean;
    no_cache?: boolean;
  }) =>
    http<Run>("/api/runs", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  listRuns: () => http<Run[]>("/api/runs"),
  getRun: (id: number) => http<Run>(`/api/runs/${id}`),
  stopRun: (id: number, graceful: boolean) =>
    http<Run>(`/api/runs/${id}/stop`, {
      method: "POST",
      body: JSON.stringify({ graceful }),
    }),
  getRunLog: (id: number) =>
    http<{ text: string; path: string }>(`/api/runs/${id}/log`),

  listApplications: (params?: {
    run_id?: number;
    status?: ApplicationStatus;
  }) => {
    const qs = new URLSearchParams();
    if (params?.run_id != null) qs.set("run_id", String(params.run_id));
    if (params?.status) qs.set("status", params.status);
    const q = qs.toString();
    return http<Application[]>(`/api/applications${q ? `?${q}` : ""}`);
  },
  getApplication: (id: number) => http<Application>(`/api/applications/${id}`),
  patchApplication: (
    id: number,
    body: Partial<
      Pick<Application, "status" | "notes" | "tags" | "applied_at" | "deadline">
    >,
  ) =>
    http<Application>(`/api/applications/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  bulkUpdateApplications: (
    ids: number[],
    body: { status?: ApplicationStatus; add_tags?: string[] },
  ) =>
    http<Application[]>(`/api/applications/bulk`, {
      method: "POST",
      body: JSON.stringify({ ids, ...body }),
    }),
  exportApplicationsCsv: async (ids: number[] = []) => {
    const res = await fetch(`${API_BASE}/api/applications/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }),
      cache: "no-store",
    });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "applications.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },

  extractJob: (url: string) =>
    http<{
      company: string;
      title: string;
      location: string;
      remote: boolean;
      description: string;
      additional_questions: string[];
      specific_instructions: string;
      url: string;
    }>("/api/single-job/extract", {
      method: "POST",
      body: JSON.stringify({ url }),
    }),

  getStats: () => http<StatsResponse>("/api/stats"),

  listProviders: () => http<ProviderInfo[]>("/api/providers"),
  testProvider: (provider: string) =>
    http<ProviderTestResult>("/api/providers/test", {
      method: "POST",
      body: JSON.stringify({ provider }),
    }),

  // ----- Per-workflow LLM routing -----
  getLlmConfig: () => http<LlmConfig>("/api/llm-config"),
  putLlmConfig: (body: {
    global: { primary: string | null; fallbacks: string[] };
    tasks: Record<
      string,
      { primary?: string | null; fallbacks?: string[]; models?: Record<string, string> }
    >;
  }) =>
    http<{ ok: boolean }>("/api/llm-config", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  // ----- LLM-assisted master data -----
  generateStory: (body: { description: string; provider?: string }) =>
    http<GeneratedStory>("/api/master-data/stories/generate", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  tweakContent: (body: {
    kind: "story" | "bio" | "resume";
    text: string;
    instruction: string;
    provider?: string;
  }) =>
    http<{ text: string }>("/api/master-data/tweak", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  compareRuns: (a: number, b: number) =>
    http<RunCompare>(`/api/compare?a=${a}&b=${b}`),

  listRankedJobs: (
    runId: number,
    only: "all" | "selected" | "rejected" | "generated" | "dismissed" = "all",
  ) => http<RankedJob[]>(`/api/runs/${runId}/ranked?only=${only}`),
  generateRanked: (rankedId: number) =>
    http<{ run_id: number }>(`/api/ranked/${rankedId}/generate`, {
      method: "POST",
    }),
  dismissRanked: (rankedId: number, dismissed: boolean) =>
    http<RankedJob>(`/api/ranked/${rankedId}/dismiss`, {
      method: "POST",
      body: JSON.stringify({ dismissed }),
    }),

  // Close-the-loop: inbox sync + reminders
  inboxStatus: () => http<InboxStatus>("/api/inbox/status"),
  inboxTest: () => http<{ ok: boolean }>("/api/inbox/test", { method: "POST" }),
  inboxSync: (days?: number) =>
    http<InboxSyncResult>("/api/inbox/sync", {
      method: "POST",
      body: JSON.stringify({ days: days ?? null }),
    }),
  remindersStatus: () => http<RemindersStatus>("/api/reminders/status"),
  digestPreview: () => http<DigestPreview>("/api/reminders/digest/preview"),
  digestSend: () =>
    http<{ sent: boolean; to: string }>("/api/reminders/digest/send", {
      method: "POST",
    }),
  calendarUrl: () => `${API_BASE}/api/calendar.ics`,

  listResumeVersions: (id: number) =>
    http<{ versions: ResumeVersion[] }>(
      `/api/applications/${id}/resume-versions`,
    ),
  tweakResume: (id: number, instruction: string, provider?: string) =>
    http<{
      docx_filename: string;
      pdf_filename: string | null;
      version: number;
    }>(`/api/applications/${id}/tweak`, {
      method: "POST",
      body: JSON.stringify({ instruction, provider }),
    }),

  getCoverLetter: (id: number) =>
    http<{ text: string; has_text: boolean }>(
      `/api/applications/${id}/cover-letter`,
    ),
  saveCoverLetter: (id: number, text: string) =>
    http<{ ok: boolean; pdf_filename: string | null }>(
      `/api/applications/${id}/cover-letter`,
      { method: "PUT", body: JSON.stringify({ text }) },
    ),

  // ----- Onboarding / first-run setup -----
  onboardingStatus: () => http<OnboardingStatus>("/api/onboarding/status"),
  onboardingComplete: () =>
    http<OnboardingStatus>("/api/onboarding/complete", { method: "POST" }),
  onboardingReset: () =>
    http<OnboardingStatus>("/api/onboarding/reset", { method: "POST" }),
  setOnboardingUser: (body: {
    full_name: string;
    email: string;
    phone?: string;
    location_city?: string;
    linkedin?: string;
    github?: string;
    portfolio?: string;
  }) =>
    http<OnboardingStatus>("/api/onboarding/user", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  setOnboardingProvider: (body: {
    provider: string;
    api_key?: string;
    model?: string;
    base_url?: string;
    make_primary?: boolean;
  }) =>
    http<OnboardingStatus>("/api/onboarding/provider", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  setOnboardingSearch: (body: {
    keywords: string[];
    remote_ok?: boolean;
    onsite_cities?: string[];
    countries?: string[];
    max_jobs_per_day?: number;
    min_match_score?: number;
  }) =>
    http<OnboardingStatus>("/api/onboarding/search", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  importResumeText: (body: { text: string; provider?: string }) =>
    http<{ text: string; fields: unknown }>(
      "/api/onboarding/resume-import-text",
      { method: "POST", body: JSON.stringify(body) },
    ),
  importResumeFile: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE}/api/onboarding/resume-import`, {
      method: "POST",
      body: form,
      cache: "no-store",
    });
    if (!res.ok) {
      let detail = "";
      try {
        detail = await res.text();
      } catch {}
      throw new Error(`${res.status} ${res.statusText}: ${detail}`);
    }
    return res.json() as Promise<{ text: string; fields: unknown }>;
  },

  getConfig: () => http<{ text: string }>("/api/config"),
  putConfig: (text: string) =>
    http<{ ok: boolean }>("/api/config", {
      method: "PUT",
      body: JSON.stringify({ text }),
    }),

  getResume: () => http<{ text: string }>("/api/master-data/resume"),
  putResume: (text: string) =>
    http<{ ok: boolean }>("/api/master-data/resume", {
      method: "PUT",
      body: JSON.stringify({ text }),
    }),

  getBio: () => http<{ text: string }>("/api/master-data/bio"),
  putBio: (text: string) =>
    http<{ ok: boolean }>("/api/master-data/bio", {
      method: "PUT",
      body: JSON.stringify({ text }),
    }),

  listStories: () =>
    http<{ name: string; size: number }[]>("/api/master-data/stories"),
  getStory: (name: string) =>
    http<{ name: string; text: string }>(
      `/api/master-data/stories/${encodeURIComponent(name)}`,
    ),
  putStory: (name: string, text: string) =>
    http<{ ok: boolean }>(
      `/api/master-data/stories/${encodeURIComponent(name)}`,
      {
        method: "PUT",
        body: JSON.stringify({ text }),
      },
    ),

  generateSingle: (body: {
    company: string;
    title: string;
    location: string;
    remote: boolean;
    description: string;
    url: string;
    additional_questions: string[];
    specific_instructions: string;
  }) =>
    http<{ run_id: number }>("/api/single-job/generate", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // ----- Coach / Prepwork (conversational assistant) -----
  createChatSession: (body: {
    title?: string;
    application_id?: number;
    mode?: ChatMode;
  }) =>
    http<ChatSession>("/api/chat/sessions", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listChatSessions: (mode?: ChatMode) =>
    http<ChatSession[]>(
      `/api/chat/sessions${mode ? `?mode=${mode}` : ""}`,
    ),
  getChatSession: (id: number) =>
    http<ChatSessionDetail>(`/api/chat/sessions/${id}`),
  // PATCH accepts title and/or application_id (null clears grounding).
  updateChatSession: (
    id: number,
    body: { title?: string; application_id?: number | null },
  ) =>
    http<ChatSession>(`/api/chat/sessions/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  renameChatSession: (id: number, title: string) =>
    http<ChatSession>(`/api/chat/sessions/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  deleteChatSession: (id: number) =>
    http<{ ok: boolean }>(`/api/chat/sessions/${id}`, { method: "DELETE" }),
  sendChatMessage: (id: number, content: string) =>
    http<PostMessageResult>(`/api/chat/sessions/${id}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  kickoffInterview: (id: number) =>
    http<ChatMessage>(`/api/chat/sessions/${id}/kickoff`, { method: "POST" }),
  draftEssay: (body: {
    prompt: string;
    word_limit?: number;
    application_id?: number;
    instructions?: string;
  }) =>
    http<{ content: string }>("/api/chat/essay", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // ----- Answer bank -----
  saveAnswer: (body: {
    content: string;
    title?: string;
    prompt?: string;
    tags?: string[];
    source_message_id?: number;
    application_id?: number;
  }) =>
    http<SavedAnswer>("/api/chat/answers", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listSavedAnswers: (applicationId?: number) =>
    http<SavedAnswer[]>(
      `/api/chat/answers${applicationId != null ? `?application_id=${applicationId}` : ""}`,
    ),
  deleteSavedAnswer: (id: number) =>
    http<{ ok: boolean }>(`/api/chat/answers/${id}`, { method: "DELETE" }),
  attachAnswer: (id: number, applicationId: number) =>
    http<{ ok: boolean; answers_file: string }>(
      `/api/chat/answers/${id}/attach`,
      { method: "POST", body: JSON.stringify({ application_id: applicationId }) },
    ),
};

export function fileUrl(folderRel: string, filename: string): string {
  if (!folderRel || !filename) return "";
  const parts = folderRel.split("/").filter(Boolean);
  // folder_rel is "YYYY-MM-DD/Company_Role"; /files mounts at output/ root which already
  // contains date folders, so use the date+folder pair directly.
  return `${API_BASE}/files/${parts.map(encodeURIComponent).join("/")}/${encodeURIComponent(filename)}`;
}

/**
 * Download URL for a document with a friendly, ATS-ready filename
 * (e.g. Sanchit_Arora_resume_Cloudflare.pdf). Routes through the API so the
 * server can set Content-Disposition — the <a download> hint is ignored
 * cross-origin, so this is the only reliable way to name the saved file.
 */
export function downloadUrl(
  appId: number,
  doc: "resume" | "cover",
  fmt: "pdf" | "docx",
  version?: number,
): string {
  const qs = new URLSearchParams({ doc, fmt });
  if (version && version > 1) qs.set("version", String(version));
  return `${API_BASE}/api/applications/${appId}/download?${qs.toString()}`;
}

export function subscribeRun(
  runId: number,
  onEvent: (e: PipelineEvent) => void,
  onError?: (err: Event) => void,
): () => void {
  const source = new EventSource(`${API_BASE}/api/runs/${runId}/stream`);
  source.onmessage = (evt) => {
    try {
      const parsed = JSON.parse(evt.data) as PipelineEvent;
      onEvent(parsed);
      if (
        parsed.type === "done" ||
        parsed.type === "error" ||
        parsed.type === "cancelled"
      ) {
        source.close();
      }
    } catch (e) {
      console.error("bad SSE payload", e, evt.data);
    }
  };
  source.onerror = (err) => {
    if (onError) onError(err);
    source.close();
  };
  return () => source.close();
}
