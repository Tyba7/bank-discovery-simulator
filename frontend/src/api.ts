// Typed client for the FastAPI backend. Every failure becomes an ApiError with a message fit to show the student.

export interface ClientCard {
  id: string;
  name: string;
  age: number;
  occupation: string;
  background: string;
  stated_goal: string;
}

export interface ProductCard {
  id: string;
  name: string;
  category: string;
  features: string[];
  limitations: string[];
}

export interface Message {
  role: "student" | "client";
  content: string;
}

export interface Recommendation {
  product_id: string;
  reason: string;
}

export interface NeedResult {
  id: string;
  category: string;
  topic: string;
  fact: string;
  discovered: boolean;
  turn: number | null;
  question: string | null;
}

export interface ProductResult {
  id: string;
  name: string;
  recommended: boolean;
  student_reason: string;
  discussed_turns: number[];
  verdict: string;
  outcome: "suitable" | "unsuitable" | "neutral" | "investigate";
  reasons: string[];
  to_check: string[];
  assessment: string; // from the bank's rules: always shown first
  comment: string; // the coach's explanation: secondary, may be empty
}

export interface Feedback {
  client_id: string;
  source: "coach" | "rules";
  needs: NeedResult[];
  went_well: { turn: number; quote: string; point: string }[];
  missed_needs: {
    need_id: string;
    category: string;
    fact: string;
    why_it_matters: string;
    better_question: string;
    checked: boolean;
  }[];
  products: ProductResult[];
  summary: { confirmed: string[]; left_out: string[]; unconfirmed: string[]; feedback: string };
  question_feedback: string;
  next_steps: string[];
  question_stats: Record<string, number>;
}

export interface Session {
  session_id: string;
  client: ClientCard;
  messages: Message[];
  turns_left: number;
  finished: boolean;
  feedback: Feedback | null;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError("Cannot reach the server. Check that it is running and try again.", 0);
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail;
    // FastAPI validation errors are a list; everything else from our API is a plain sentence.
    const message = Array.isArray(detail)
      ? detail.map((d: { msg?: string }) => d.msg).join("; ")
      : typeof detail === "string"
        ? detail
        : `Request failed (${response.status}).`;
    throw new ApiError(message, response.status);
  }
  return body as T;
}

const post = <T>(path: string, data: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(data) });

export const api = {
  clients: () => request<ClientCard[]>("/api/clients"),
  products: () => request<ProductCard[]>("/api/products"),
  start: (clientId: string) => post<Session>("/api/sessions", { client_id: clientId }),
  session: (id: string) => request<Session>(`/api/sessions/${encodeURIComponent(id)}`),
  send: (id: string, message: string) =>
    post<{ reply: string; turns_left: number }>(`/api/sessions/${encodeURIComponent(id)}/messages`, { message }),
  feedback: (id: string, summary: string, recommendations: Recommendation[]) =>
    post<Feedback>(`/api/sessions/${encodeURIComponent(id)}/feedback`, { summary, recommendations }),
  exportUrl: (id: string) => `/api/sessions/${encodeURIComponent(id)}/export`,
};

export const MAX_MESSAGE_CHARS = 1000;
export const MAX_SUMMARY_CHARS = 2000;
export const MAX_REASON_CHARS = 500;
