import type {
  AgentSpec,
  ConversationDetail,
  ConversationSummary,
  RunResponse,
  UploadOut,
} from "./types";

const BASE = "/api/v1";

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function parse<T>(res: Response): Promise<T> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) {
    const err = (body as { error?: { code?: string; message?: string } })?.error;
    throw new ApiError(
      res.status,
      err?.code ?? "http_error",
      err?.message ?? `HTTP ${res.status}`,
    );
  }
  return body as T;
}

export const api = {
  agents: async (): Promise<AgentSpec[]> => parse(await fetch(`${BASE}/agents`)),

  createRun: async (body: Record<string, unknown>): Promise<RunResponse> =>
    parse(
      await fetch(`${BASE}/runs`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      }),
    ),

  getRun: async (runId: string): Promise<RunResponse> =>
    parse(await fetch(`${BASE}/runs/${runId}`)),

  cancelRun: async (runId: string): Promise<RunResponse> =>
    parse(
      await fetch(`${BASE}/runs/${runId}/cancel`, { method: "POST" }),
    ),

  conversations: async (): Promise<ConversationSummary[]> =>
    parse(await fetch(`${BASE}/conversations`)),

  conversation: async (id: string): Promise<ConversationDetail> =>
    parse(await fetch(`${BASE}/conversations/${encodeURIComponent(id)}`)),

  deleteConversation: async (id: string): Promise<void> => {
    const res = await fetch(`${BASE}/conversations/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
    if (!res.ok) await parse<never>(res);
  },

  upload: async (file: File): Promise<UploadOut> => {
    const form = new FormData();
    form.append("file", file, file.name);
    return parse(
      await fetch(`${BASE}/uploads`, { method: "POST", body: form }),
    );
  },
};
