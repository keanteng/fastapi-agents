import "./style.css";

type RunStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

interface AgentSpec {
  name: string;
  description: string;
  instructions_key: string;
  output_type: "string" | "structured_output";
  output_schema: Record<string, unknown> | null;
  tools: string[];
  capabilities: string[];
  uses_memory: boolean;
  default_max_steps: number;
}

interface RunStep {
  index: number;
  type: string;
  name: string;
  summary: string;
  result: string | null;
  started_at: string;
  finished_at: string | null;
}

interface RunResponse {
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

interface RunEvent {
  type: string;
  run_id: string;
  sequence: number;
  created_at: string;
  data: Record<string, unknown>;
}

const TERMINAL_EVENTS = new Set(["response.completed", "response.failed", "run.cancelled"]);
const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);

const agentSelect = document.querySelector<HTMLSelectElement>("#agent")!;
const inputField = document.querySelector<HTMLTextAreaElement>("#input")!;
const maxSteps = document.querySelector<HTMLInputElement>("#max-steps")!;
const startBtn = document.querySelector<HTMLButtonElement>("#start")!;
const cancelBtn = document.querySelector<HTMLButtonElement>("#cancel")!;
const continueConv = document.querySelector<HTMLInputElement>("#continue-conv")!;
const resetConvBtn = document.querySelector<HTMLButtonElement>("#reset-conv")!;
const runIdEl = document.querySelector<HTMLElement>("#run-id")!;
const statusEl = document.querySelector<HTMLElement>("#status")!;
const conversationEl = document.querySelector<HTMLElement>("#conversation")!;
const logEl = document.querySelector<HTMLElement>("#log")!;

let currentRunId: string | null = null;
let currentConversationId: string | null = null;
let eventSource: EventSource | null = null;
let pollTimer: number | null = null;

async function fetchAgents(): Promise<void> {
  const res = await fetch("/api/v1/agents");
  if (!res.ok) throw new Error(`GET /agents -> ${res.status}`);
  const agents: AgentSpec[] = await res.json();
  for (const agent of agents) {
    const opt = document.createElement("option");
    opt.value = agent.name;
    opt.textContent = `${agent.name} — ${agent.description}`;
    agentSelect.append(opt);
  }
}

function appendLog(line: string): void {
  logEl.append(line + "\n");
  logEl.scrollTop = logEl.scrollHeight;
}

function setStatus(status: string): void {
  statusEl.textContent = status;
  statusEl.className = `status-${status}`;
}

function setRunning(running: boolean): void {
  startBtn.disabled = running;
  cancelBtn.disabled = !running;
}

function startPolling(): void {
  stopPolling();
  pollTimer = window.setInterval(() => {
    void refreshRun();
  }, 1500);
}

function stopPolling(): void {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function startRun(event: Event): Promise<void> {
  event.preventDefault();
  const body: Record<string, unknown> = {
    agent: agentSelect.value,
    input: inputField.value,
  };
  if (continueConv.checked && currentConversationId) {
    body.conversation_id = currentConversationId;
  }
  const steps = maxSteps.value.trim();
  if (steps !== "") {
    body.max_steps = Number(steps);
  }
  const res = await fetch("/api/v1/runs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json();
    appendLog(`ERROR ${res.status}: ${JSON.stringify(err)}`);
    return;
  }
  const run: RunResponse = await res.json();
  currentRunId = run.run_id;
  runIdEl.textContent = run.run_id;
  conversationEl.textContent = run.conversation_id ?? "—";
  logEl.textContent = "";
  appendLog(`created run ${run.run_id} (${run.agent})`);
  if (body.conversation_id) {
    appendLog(`continuing conversation ${body.conversation_id}`);
  }
  setStatus(run.status);
  setRunning(true);
  openStream(run.run_id);
}

function openStream(runId: string): void {
  eventSource?.close();
  eventSource = new EventSource(`/api/v1/runs/${runId}/events`);
  eventSource.onmessage = (msg) => {
    const event: RunEvent = JSON.parse(msg.data);
    appendLog(formatEvent(event));
    if (TERMINAL_EVENTS.has(event.type)) {
      onTerminal();
    }
  };
  eventSource.onerror = () => {
    eventSource?.close();
    eventSource = null;
    appendLog("[stream closed]");
    startPolling();
    void refreshRun();
  };
}

function formatEvent(event: RunEvent): string {
  const { type, sequence, data } = event;
  if (type === "response.output_text.delta") {
    return data.text as string;
  }
  if (type === "response.output_text.done") {
    return `\n[${type}] ${JSON.stringify(data.text)}`;
  }
  if (type === "run.step") {
    const step = data as { type: string; name: string; summary: string };
    return `[step ${sequence} · ${step.type} · ${step.name}] ${step.summary}`;
  }
  if (type === "response.completed") {
    return `\n[completed] usage=${JSON.stringify(data.usage)}`;
  }
  return `[${type}] ${JSON.stringify(data)}`;
}

async function onTerminal(): Promise<void> {
  eventSource?.close();
  eventSource = null;
  setRunning(false);
  stopPolling();
  await refreshRun();
}

async function refreshRun(): Promise<RunResponse | null> {
  if (!currentRunId) return null;
  const res = await fetch(`/api/v1/runs/${currentRunId}`);
  if (!res.ok) {
    appendLog(`ERROR GET run -> ${res.status}`);
    return null;
  }
  const run: RunResponse = await res.json();
  setStatus(run.status);
  conversationEl.textContent = run.conversation_id ?? "—";
  if (run.conversation_id) currentConversationId = run.conversation_id;
  if (TERMINAL_STATUSES.has(run.status)) {
    setRunning(false);
    stopPolling();
  } else {
    setRunning(true);
  }
  for (const artifact of run.artifacts) {
    if (artifact.kind === "text" || artifact.kind === "structured_output") {
      appendLog(`\n[artifact:${artifact.name}]\n${JSON.stringify(artifact.data, null, 2)}`);
    }
  }
  if (run.error) appendLog(`\n[error] ${run.error.code}: ${run.error.message}`);
  return run;
}

function resetConversation(): void {
  currentConversationId = null;
  conversationEl.textContent = "—";
  appendLog("[conversation reset — next run starts fresh]");
}

async function cancelRun(): Promise<void> {
  if (!currentRunId) return;
  const res = await fetch(`/api/v1/runs/${currentRunId}/cancel`, { method: "POST" });
  const run: RunResponse = await res.json();
  setStatus(run.status);
  appendLog(res.ok ? "cancel requested" : `cancel failed: ${JSON.stringify(run)}`);
}

const form = document.querySelector<HTMLFormElement>("#run-form")!;
form.addEventListener("submit", startRun);
cancelBtn.addEventListener("click", cancelRun);
resetConvBtn.addEventListener("click", resetConversation);
agentSelect.addEventListener("change", resetConversation);

void fetchAgents().catch((err) => appendLog(`ERROR loading agents: ${err}`));
