export type RunStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

export interface AgentSpec {
  name: string;
  description: string;
  tools: string[];
  capabilities: string[];
  uses_memory: boolean;
  default_max_steps: number;
}

export interface RunStep {
  index: number;
  type: "tool_call" | "message" | "progress";
  name: string;
  summary: string;
  result: string | null;
  tool_call_id: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface RunResponse {
  run_id: string;
  agent: string;
  status: RunStatus;
  conversation_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  steps: RunStep[];
  artifacts: { name: string; kind: string; data: unknown }[];
  usage: { input_tokens: number; output_tokens: number; requests: number } | null;
  error: { code: string; message: string } | null;
}

export interface RunEvent {
  type: string;
  run_id: string;
  sequence: number;
  created_at: string;
  data: Record<string, unknown>;
}

export interface ConversationSummary {
  conversation_id: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  preview: string | null;
}

export interface PartOut {
  kind: string;
  role: string;
  content: string | null;
  tool_name: string | null;
  tool_args: Record<string, unknown> | null;
  tool_call_id: string | null;
  tool_result: unknown | null;
  timestamp: string | null;
}

export interface MessageOut {
  kind: "request" | "response";
  parts: PartOut[];
}

export interface ConversationDetail {
  conversation_id: string;
  created_at: string;
  messages: MessageOut[];
}

export interface UploadOut {
  upload_id: string;
  file_name: string;
  content_type: string | null;
  size: number;
  created_at: string;
}
