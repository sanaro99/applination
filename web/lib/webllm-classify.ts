import type { MLCEngine, InitProgressReport, AppConfig } from "@mlc-ai/web-llm";

/**
 * In-browser email classification for inbox sync — ports the same
 * system/user prompt and category schema the backend's
 * `src/inbox.py::classify_email` used to send to a cloud LLM, but runs
 * locally via WebLLM so a simple 5-category label + confidence call never
 * has to hit a full cloud model. This is a deliberate one-off exception to
 * this app's usual "all LLM calls go through src/providers/" rule.
 */
export const CATEGORIES = ["auto_ack", "interview", "rejection", "offer", "other"] as const;
export type Category = (typeof CATEGORIES)[number];

export interface ClassifyCandidate {
  company: string;
  title: string;
  from_name: string;
  from_email: string;
  subject: string;
  date: string | null;
  body: string;
}

export interface ClassifyResult {
  category: Category;
  confidence: number;
  summary: string;
  interview_date: string | null;
}

const MODEL_ID = "Llama-3.2-1B-Instruct-q4f16_1-MLC";

// We self-host the model weights + wasm and serve them same-origin from
// Next's public/ dir (see web/public/models/, gitignored). WebLLM's default
// config fetches ~1GB from huggingface.co, which some networks block outright
// ("Failed to fetch" on CreateMLCEngine). Serving from our own origin makes
// inbox classification work regardless of HF reachability, and offline.
// To (re)populate the files, run: python scripts/fetch_webllm_model.py
// The `resolve/main/` suffix matches WebLLM's cleanModelUrl() expectation
// (it appends that to any model URL lacking a /resolve/<branch>/ segment), so
// files are served from web/public/models/<id>/resolve/main/.
const MODEL_BASE = "/models/Llama-3.2-1B-Instruct-q4f16_1-MLC/resolve/main/";
const MODEL_LIB = "/models/libs/Llama-3.2-1B-Instruct-q4f16_1_cs1k-webgpu.wasm";

/** AppConfig pointing WebLLM at the self-hosted, same-origin model + wasm. */
function localAppConfig(): AppConfig {
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  return {
    model_list: [
      {
        model: origin + MODEL_BASE,
        model_id: MODEL_ID,
        model_lib: origin + MODEL_LIB,
      },
    ],
  };
}

const RESPONSE_SCHEMA = JSON.stringify({
  type: "object",
  properties: {
    category: { type: "string", enum: CATEGORIES },
    confidence: { type: "number" },
    summary: { type: "string" },
    interview_date: { type: ["string", "null"] },
  },
  required: ["category", "confidence"],
});

const SYSTEM_PROMPT =
  "You triage emails a job applicant receives after applying. Decide what " +
  "an email means for ONE specific application. Categories:\n" +
  "- auto_ack: automated 'we received your application' acknowledgement.\n" +
  "- interview: invitation to interview, schedule a call, or take an " +
  "assessment/OA.\n" +
  "- rejection: the application was declined / position filled / not moving " +
  "forward.\n" +
  "- offer: a job/internship offer is extended.\n" +
  "- other: newsletters, unrelated mail, or anything that does not clearly " +
  "fit the above.\n\n" +
  "BINDING RULES: Judge ONLY from the email text. If the email is not " +
  "clearly about THIS company/role, or is ambiguous, return category " +
  "'other' with low confidence. Do not infer an outcome that the text does " +
  "not state. confidence is your certainty from 0.0 to 1.0. If the email " +
  "proposes a specific interview date/time, put it in interview_date as an " +
  "ISO 8601 string (YYYY-MM-DD or YYYY-MM-DDTHH:MM); otherwise null. " +
  "Respond with ONLY a JSON object matching the schema — no other text.";

function buildUserPrompt(c: ClassifyCandidate): string {
  return (
    `APPLICATION: ${c.title} at ${c.company}\n\n` +
    `EMAIL FROM: ${c.from_name} <${c.from_email}>\n` +
    `SUBJECT: ${c.subject}\n` +
    `DATE: ${c.date ?? "unknown"}\n\n` +
    `BODY:\n${c.body.slice(0, 2500)}`
  );
}

/** True if this browser can run WebLLM at all. */
export function webgpuSupported(): boolean {
  return typeof navigator !== "undefined" && "gpu" in navigator;
}

let enginePromise: Promise<MLCEngine> | null = null;

/** Lazily creates (and caches) the WebLLM engine, reporting load progress. */
export function getEngine(onProgress?: (r: InitProgressReport) => void): Promise<MLCEngine> {
  if (!enginePromise) {
    enginePromise = import("@mlc-ai/web-llm").then(({ CreateMLCEngine }) =>
      CreateMLCEngine(MODEL_ID, {
        appConfig: localAppConfig(),
        initProgressCallback: onProgress,
      }),
    );
  }
  return enginePromise;
}

function normalize(raw: unknown): ClassifyResult {
  const obj = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  let category = String(obj.category ?? "other").trim().toLowerCase();
  if (!CATEGORIES.includes(category as Category)) category = "other";
  let confidence = Number(obj.confidence ?? 0);
  if (!Number.isFinite(confidence)) confidence = 0;
  confidence = Math.max(0, Math.min(1, confidence));
  const summary = String(obj.summary ?? "").slice(0, 500);
  const interview_date =
    typeof obj.interview_date === "string" ? obj.interview_date : null;
  return { category: category as Category, confidence, summary, interview_date };
}

/** Classify one email locally. Never throws — falls back to a low-confidence "other". */
export async function classifyEmail(
  engine: MLCEngine,
  candidate: ClassifyCandidate,
): Promise<ClassifyResult> {
  try {
    const completion = await engine.chat.completions.create({
      messages: [
        { role: "system", content: SYSTEM_PROMPT },
        { role: "user", content: buildUserPrompt(candidate) },
      ],
      response_format: { type: "json_object", schema: RESPONSE_SCHEMA },
      max_tokens: 300,
      temperature: 0,
    });
    const text = completion.choices[0]?.message?.content ?? "{}";
    return normalize(JSON.parse(text));
  } catch (e) {
    console.warn("webllm: classify failed", e);
    return { category: "other", confidence: 0, summary: "", interview_date: null };
  }
}
